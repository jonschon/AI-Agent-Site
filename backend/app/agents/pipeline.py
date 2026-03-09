from __future__ import annotations

import hashlib
import statistics
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from slugify import slugify
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.news import (
    AgentRun,
    Article,
    ArticleEmbedding,
    DiscussionLink,
    ExceptionItem,
    FeedSnapshot,
    FeedSnapshotItem,
    RawArticle,
    RunStatus,
    Signal,
    Source,
    SourceState,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTag,
    StoryTier,
    Tag,
)
from app.services.cluster import (
    cluster_confidence,
    cosine_similarity,
    lexical_overlap,
    overlap_ratio,
    tokenize,
)
from app.services.adaptive_policy_service import tune_agent_controls
from app.services.crawler import build_synthetic_entry, fetch_feed_entries
from app.services.memory_service import get_float_control, get_memory, get_text_control, set_memory
from app.services.model_gateway import generate_embedding, infer_tags, summarize_story
from app.services.scoring import apply_retention_tier, momentum, score_story
from app.services.self_heal_service import auto_resolve_stale_low_exceptions


@dataclass
class AgentResult:
    processed: int
    created: int = 0
    updated: int = 0


def target_bullet_count(tier: StoryTier | str, importance_score: float) -> int:
    tier_value = tier.value if isinstance(tier, StoryTier) else str(tier)
    if importance_score >= 0.7:
        return 3
    if importance_score >= 0.55:
        return 2
    # Lead stories should not collapse to a single bullet even if upstream scores are noisy.
    if tier_value == StoryTier.lead.value:
        return 2
    return 1


def to_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class BaseAgent:
    name = "base"

    def run(self, db: Session) -> AgentResult:
        raise NotImplementedError

    def _start_run(self, db: Session) -> AgentRun:
        run = AgentRun(agent_name=self.name, status=RunStatus.running)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def _finish_run(self, db: Session, run: AgentRun, result: AgentResult) -> None:
        run.ended_at = datetime.now(timezone.utc)
        run.status = RunStatus.success
        run.metrics_json = {"processed": result.processed, "created": result.created, "updated": result.updated}
        db.add(run)
        db.commit()

    def _fail_run(self, db: Session, run: AgentRun, exc: Exception) -> None:
        run.ended_at = datetime.now(timezone.utc)
        run.status = RunStatus.failed
        run.error_text = str(exc)
        db.add(run)
        db.commit()


class CrawlerAgent(BaseAgent):
    name = "crawler"

    def _source_in_cooldown(self, source: Source) -> bool:
        config = dict(source.crawl_config_json or {})
        cooldown_until_raw = config.get("cooldown_until")
        if not isinstance(cooldown_until_raw, str):
            return False
        try:
            cooldown_until = datetime.fromisoformat(cooldown_until_raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=timezone.utc)
        return cooldown_until > datetime.now(timezone.utc)

    def _update_poll_minutes(
        self, source: Source, used_fallback: bool, created_for_source: int, crawl_mode: str
    ) -> None:
        config = dict(source.crawl_config_json or {})
        poll = int(config.get("poll_minutes", settings.crawl_interval_minutes))
        if crawl_mode == "aggressive":
            if used_fallback or created_for_source == 0:
                poll = min(settings.self_heal_max_poll_minutes, poll + 1)
            elif created_for_source >= 3:
                poll = max(settings.self_heal_min_poll_minutes, poll - 2)
        elif crawl_mode == "conservative":
            if used_fallback or created_for_source == 0:
                poll = min(settings.self_heal_max_poll_minutes, poll + 3)
            elif created_for_source >= 8:
                poll = max(settings.self_heal_min_poll_minutes, poll - 1)
        else:
            if used_fallback or created_for_source == 0:
                poll = min(settings.self_heal_max_poll_minutes, poll + 2)
            elif created_for_source >= 5:
                poll = max(settings.self_heal_min_poll_minutes, poll - 1)
        config["poll_minutes"] = poll
        config["crawl_mode"] = crawl_mode
        source.crawl_config_json = config

    def _record_source_failure(self, db: Session, source: Source, reason: str) -> None:
        now = datetime.now(timezone.utc)
        config = dict(source.crawl_config_json or {})
        failures = int(config.get("crawl_failures", 0)) + 1
        config["crawl_failures"] = failures
        config["last_failure_at"] = now.isoformat()

        if failures >= settings.self_heal_max_source_failures:
            config["cooldown_until"] = (
                now + timedelta(minutes=settings.self_heal_source_cooldown_minutes)
            ).isoformat()
            source.state = SourceState.watchlist

        source.crawl_config_json = config
        db.add(
            ExceptionItem(
                agent_name=self.name,
                object_type="source",
                object_id=str(source.id),
                reason=f"Crawler source failure: {reason}",
                severity="high" if failures >= settings.self_heal_max_source_failures else "medium",
                payload_json={
                    "source_name": source.name,
                    "domain": source.domain,
                    "crawl_failures": failures,
                    "cooldown_until": config.get("cooldown_until"),
                },
            )
        )

    def _record_source_success(self, source: Source) -> None:
        config = dict(source.crawl_config_json or {})
        config["crawl_failures"] = 0
        config["last_success_at"] = datetime.now(timezone.utc).isoformat()
        config.pop("cooldown_until", None)
        source.crawl_config_json = config
        if source.state == SourceState.watchlist:
            source.state = SourceState.trusted

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            sources = db.execute(select(Source).where(Source.is_active == True)).scalars().all()  # noqa: E712
            if sources:
                # Rotate source order each cycle so global caps do not consistently favor the same sources.
                cycle_seconds = max(settings.publish_interval_minutes * 60, 60)
                cycle_index = int(datetime.now(timezone.utc).timestamp() // cycle_seconds)
                offset = cycle_index % len(sources)
                sources = sources[offset:] + sources[:offset]
            created = 0
            updated = 0
            remaining_cycle_budget = settings.crawler_max_new_articles_per_cycle
            crawl_mode = get_text_control(db, "crawl_aggressiveness", "normal")
            for source in sources:
                if remaining_cycle_budget <= 0:
                    break
                if self._source_in_cooldown(source):
                    updated += 1
                    continue

                source_budget = min(settings.crawler_max_new_articles_per_source, remaining_cycle_budget)
                used_fallback = False
                try:
                    entries = fetch_feed_entries(source, limit=settings.crawler_fetch_limit_per_source)
                except Exception as exc:  # noqa: BLE001
                    self._record_source_failure(db, source, str(exc))
                    updated += 1
                    continue

                if not entries:
                    entries = [build_synthetic_entry(source)]
                    used_fallback = True

                created_for_source = 0
                for entry in entries:
                    if created_for_source >= source_budget or remaining_cycle_budget <= 0:
                        break
                    exists = db.execute(
                        select(RawArticle).where(RawArticle.raw_url == entry["url"]).limit(1)
                    ).scalar_one_or_none()
                    if exists:
                        continue
                    raw = RawArticle(
                        source_id=source.id,
                        raw_url=entry["url"],
                        payload_json={
                            "title": entry["title"],
                            "content": entry["content"],
                            "image_url": entry.get("image_url"),
                            "published_at": entry["published_at"],
                            "fingerprint": entry["fingerprint"],
                            "feed_url": entry["feed_url"],
                        },
                    )
                    db.add(raw)
                    created += 1
                    created_for_source += 1
                    remaining_cycle_budget -= 1

                self._record_source_success(source)
                self._update_poll_minutes(
                    source,
                    used_fallback=used_fallback,
                    created_for_source=created_for_source,
                    crawl_mode=crawl_mode,
                )
                updated += 1
            db.commit()
            result = AgentResult(processed=len(sources), created=created, updated=updated)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class NormalizationAgent(BaseAgent):
    name = "normalization"

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            raws = db.execute(select(RawArticle).order_by(desc(RawArticle.id)).limit(30)).scalars().all()
            created = 0
            for raw in raws:
                exists = db.execute(select(Article).where(Article.canonical_url == raw.raw_url)).scalar_one_or_none()
                if exists:
                    continue
                content = raw.payload_json.get("content", "")
                published_at_raw = raw.payload_json.get("published_at")
                published_at = datetime.now(timezone.utc)
                if isinstance(published_at_raw, str):
                    try:
                        published_at = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
                    except ValueError:
                        published_at = datetime.now(timezone.utc)
                article = Article(
                    source_id=raw.source_id,
                    canonical_url=raw.raw_url,
                    title=raw.payload_json.get("title", "Untitled"),
                    content_text=content,
                    snippet=content[:200],
                    published_at=published_at,
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    language="en",
                )
                db.add(article)
                created += 1
            db.commit()
            result = AgentResult(processed=len(raws), created=created)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class EmbeddingAgent(BaseAgent):
    name = "embedding"

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            articles = db.execute(select(Article).order_by(desc(Article.id)).limit(40)).scalars().all()
            created = 0
            for article in articles:
                exists = db.execute(
                    select(ArticleEmbedding).where(ArticleEmbedding.article_id == article.id)
                ).scalar_one_or_none()
                if exists:
                    continue
                embedding = generate_embedding(f"{article.title}\n{article.snippet or ''}")
                db.add(
                    ArticleEmbedding(
                        article_id=article.id,
                        embedding=embedding,
                        model_name="deterministic-mvp",
                    )
                )
                created += 1
            db.commit()
            result = AgentResult(processed=len(articles), created=created)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class ClusteringAgent(BaseAgent):
    name = "clustering"

    def _story_embedding(self, db: Session, story_id: int) -> list[float]:
        embeddings = db.execute(
            select(ArticleEmbedding.embedding)
            .join(StoryArticle, StoryArticle.article_id == ArticleEmbedding.article_id)
            .where(StoryArticle.story_id == story_id)
            .order_by(desc(StoryArticle.added_at))
            .limit(4)
        ).scalars().all()
        if not embeddings:
            return []

        size = len(embeddings[0])
        sums = [0.0] * size
        valid_count = 0
        for embedding in embeddings:
            if not isinstance(embedding, list) or len(embedding) != size:
                continue
            for idx, value in enumerate(embedding):
                sums[idx] += float(value)
            valid_count += 1
        if valid_count == 0:
            return []
        return [value / valid_count for value in sums]

    def _find_candidate_story(
        self, db: Session, article: Article, article_embedding: list[float], min_confidence: float
    ) -> tuple[Story | None, float]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.clustering_window_hours)
        candidates = db.execute(
            select(Story)
            .where(Story.status == StoryStatus.active, Story.last_updated_at >= cutoff)
            .order_by(desc(Story.last_updated_at))
            .limit(60)
        ).scalars().all()

        article_tokens = tokenize(article.title or "")
        article_entities = [token for token in (article.title or "").split() if token[:1].isupper()]
        best_story: Story | None = None
        best_confidence = 0.0

        for story in candidates:
            story_vector = self._story_embedding(db, story.id)
            semantic = cosine_similarity(article_embedding, story_vector) if story_vector else 0.0

            story_tokens = tokenize(story.headline or "")
            lexical = lexical_overlap(article_tokens, story_tokens)

            story_entities = [token for token in (story.headline or "").split() if token[:1].isupper()]
            entity_score = overlap_ratio(article_entities, story_entities)

            confidence = cluster_confidence(semantic=semantic, lexical=lexical, entity_overlap=entity_score)
            if confidence > best_confidence:
                best_confidence = confidence
                best_story = story

        if best_confidence < min_confidence:
            return None, best_confidence
        return best_story, best_confidence

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            articles = db.execute(select(Article).order_by(desc(Article.published_at)).limit(40)).scalars().all()
            created = 0
            updated = 0
            dynamic_min_confidence = get_float_control(
                db, "clustering_min_confidence", settings.clustering_min_confidence
            )
            for article in articles:
                linked = db.execute(
                    select(StoryArticle).where(StoryArticle.article_id == article.id)
                ).scalar_one_or_none()
                if linked:
                    continue

                embedding_row = db.execute(
                    select(ArticleEmbedding).where(ArticleEmbedding.article_id == article.id)
                ).scalar_one_or_none()
                article_embedding = embedding_row.embedding if embedding_row else generate_embedding(article.title)
                if not embedding_row:
                    db.add(
                        ArticleEmbedding(
                            article_id=article.id,
                            embedding=article_embedding,
                            model_name="on-demand-clustering",
                        )
                    )
                    db.flush()

                story, confidence = self._find_candidate_story(
                    db, article, article_embedding, min_confidence=dynamic_min_confidence
                )

                if not story:
                    headline, bullets = summarize_story(article.title, [article.snippet or article.content_text])
                    story = Story(
                        slug=slugify(headline)[:280],
                        headline=headline,
                        bullets_json=bullets,
                        tier=StoryTier.quick,
                    )
                    db.add(story)
                    db.flush()
                    created += 1
                    confidence = 1.0
                else:
                    updated += 1

                db.add(
                    StoryArticle(
                        story_id=story.id,
                        article_id=article.id,
                        cluster_confidence=confidence,
                        is_primary=False,
                    )
                )
                story.last_updated_at = datetime.now(timezone.utc)

                if confidence < settings.clustering_exception_floor:
                    db.add(
                        ExceptionItem(
                            agent_name=self.name,
                            object_type="article",
                            object_id=str(article.id),
                            reason="Low-confidence cluster assignment",
                            severity="medium",
                            payload_json={"confidence": confidence, "story_id": story.id},
                        )
                    )
            db.commit()

            result = AgentResult(processed=len(articles), created=created, updated=updated)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class MergeClustersAgent(BaseAgent):
    name = "merge_clusters"

    def _story_embedding(self, db: Session, story_id: int) -> list[float]:
        embeddings = db.execute(
            select(ArticleEmbedding.embedding)
            .join(StoryArticle, StoryArticle.article_id == ArticleEmbedding.article_id)
            .where(StoryArticle.story_id == story_id)
            .order_by(desc(StoryArticle.added_at))
            .limit(6)
        ).scalars().all()
        if not embeddings:
            return []

        size = len(embeddings[0])
        sums = [0.0] * size
        valid_count = 0
        for embedding in embeddings:
            if not isinstance(embedding, list) or len(embedding) != size:
                continue
            for idx, value in enumerate(embedding):
                sums[idx] += float(value)
            valid_count += 1
        if valid_count == 0:
            return []
        return [value / valid_count for value in sums]

    def _merge_story_into(self, db: Session, target: Story, source: Story, confidence: float) -> None:
        # Move article links from duplicate cluster into the canonical story.
        source_links = db.execute(
            select(StoryArticle).where(StoryArticle.story_id == source.id).order_by(desc(StoryArticle.added_at))
        ).scalars().all()
        for link in source_links:
            existing = db.execute(
                select(StoryArticle).where(
                    StoryArticle.story_id == target.id, StoryArticle.article_id == link.article_id
                )
            ).scalar_one_or_none()
            if existing:
                existing.cluster_confidence = max(existing.cluster_confidence, link.cluster_confidence)
                db.delete(link)
            else:
                link.story_id = target.id
                link.cluster_confidence = max(link.cluster_confidence, confidence)
                db.add(link)

        source_tags = db.execute(select(StoryTag).where(StoryTag.story_id == source.id)).scalars().all()
        for tag_rel in source_tags:
            existing_tag = db.execute(
                select(StoryTag).where(StoryTag.story_id == target.id, StoryTag.tag_id == tag_rel.tag_id)
            ).scalar_one_or_none()
            if existing_tag:
                existing_tag.confidence = max(existing_tag.confidence, tag_rel.confidence)
                db.delete(tag_rel)
            else:
                tag_rel.story_id = target.id
                db.add(tag_rel)

        source_discussions = db.execute(
            select(DiscussionLink).where(DiscussionLink.story_id == source.id)
        ).scalars().all()
        for discussion in source_discussions:
            existing_discussion = db.execute(
                select(DiscussionLink).where(
                    DiscussionLink.story_id == target.id, DiscussionLink.url == discussion.url
                )
            ).scalar_one_or_none()
            if existing_discussion:
                existing_discussion.engagement_score = max(
                    existing_discussion.engagement_score, discussion.engagement_score
                )
                db.delete(discussion)
            else:
                discussion.story_id = target.id
                db.add(discussion)

        target.last_updated_at = datetime.now(timezone.utc)
        target.importance_score = max(target.importance_score, source.importance_score)
        target.momentum_score = max(target.momentum_score, source.momentum_score)

        source.status = StoryStatus.archived
        source.tier = StoryTier.archived
        source.last_updated_at = datetime.now(timezone.utc)

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.story_merge_window_hours)
            stories = db.execute(
                select(Story)
                .where(Story.status == StoryStatus.active, Story.last_updated_at >= cutoff)
                .order_by(desc(Story.importance_score), desc(Story.last_updated_at))
                .limit(settings.story_merge_max_candidates)
            ).scalars().all()

            merged_count = 0
            archived_ids: set[int] = set()
            embeddings_cache: dict[int, list[float]] = {}

            for idx, primary in enumerate(stories):
                if primary.id in archived_ids or primary.status != StoryStatus.active:
                    continue

                primary_embedding = embeddings_cache.get(primary.id)
                if primary_embedding is None:
                    primary_embedding = self._story_embedding(db, primary.id)
                    embeddings_cache[primary.id] = primary_embedding

                primary_tokens = tokenize(primary.headline or "")
                primary_entities = [t for t in (primary.headline or "").split() if t[:1].isupper()]

                for candidate in stories[idx + 1 :]:
                    if candidate.id in archived_ids or candidate.status != StoryStatus.active:
                        continue

                    candidate_embedding = embeddings_cache.get(candidate.id)
                    if candidate_embedding is None:
                        candidate_embedding = self._story_embedding(db, candidate.id)
                        embeddings_cache[candidate.id] = candidate_embedding

                    semantic = cosine_similarity(primary_embedding, candidate_embedding)
                    lexical = lexical_overlap(primary_tokens, tokenize(candidate.headline or ""))
                    entity = overlap_ratio(
                        primary_entities,
                        [t for t in (candidate.headline or "").split() if t[:1].isupper()],
                    )
                    confidence = cluster_confidence(semantic=semantic, lexical=lexical, entity_overlap=entity)

                    if confidence < settings.story_merge_min_confidence:
                        continue

                    primary_articles = db.execute(
                        select(StoryArticle).where(StoryArticle.story_id == primary.id)
                    ).scalars().all()
                    candidate_articles = db.execute(
                        select(StoryArticle).where(StoryArticle.story_id == candidate.id)
                    ).scalars().all()

                    target = primary
                    source = candidate
                    if len(candidate_articles) > len(primary_articles):
                        target = candidate
                        source = primary

                    self._merge_story_into(db, target=target, source=source, confidence=confidence)
                    archived_ids.add(source.id)
                    merged_count += 1
            db.commit()

            result = AgentResult(processed=len(stories), updated=merged_count)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class SummarizationTaggingAgent(BaseAgent):
    name = "summarization_tagging"

    def _summary_signature(self, story: Story, articles: list[Article], bullet_count: int) -> str:
        parts = [str(story.id), str(bullet_count), f"tier:{story.tier.value}"]
        for article in articles:
            parts.append(f"{article.id}:{article.content_hash}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            stories = db.execute(select(Story).order_by(desc(Story.last_updated_at)).limit(40)).scalars().all()
            updated = 0
            for story in stories:
                articles = db.execute(
                    select(Article)
                    .join(StoryArticle, StoryArticle.article_id == Article.id)
                    .where(StoryArticle.story_id == story.id)
                    .order_by(desc(Article.published_at))
                    .limit(3)
                ).scalars().all()
                snippets = [a.snippet or a.content_text for a in articles]
                headline_seed = articles[0].title if articles else story.headline
                bullet_count = target_bullet_count(story.tier, story.importance_score)
                headline = story.headline
                signature = self._summary_signature(story, articles, bullet_count)
                memory_key = f"summary_signature:{story.id}"
                signature_row = get_memory(db, memory_key)
                current_signature = (signature_row.value_json or {}).get("value") if signature_row else None
                has_valid_existing_summary = bool((story.headline or "").strip()) and 1 <= len(story.bullets_json or []) <= 3
                should_resummarize = not (
                    settings.summarization_skip_unchanged
                    and has_valid_existing_summary
                    and current_signature == signature
                )

                if should_resummarize:
                    headline, bullets = summarize_story(headline_seed, snippets, max_bullets=bullet_count)
                    story.headline = headline
                    story.bullets_json = bullets
                    set_memory(
                        db,
                        memory_key,
                        {
                            "value": signature,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "updated_by": self.name,
                        },
                    )

                tags = infer_tags(f"{headline} {' '.join(snippets)}")
                for tag_name in tags:
                    tag = db.execute(select(Tag).where(Tag.name == tag_name)).scalar_one_or_none()
                    if not tag:
                        tag = Tag(name=tag_name, type="category")
                        db.add(tag)
                        db.flush()
                    exists = db.execute(
                        select(StoryTag).where(StoryTag.story_id == story.id, StoryTag.tag_id == tag.id)
                    ).scalar_one_or_none()
                    if not exists:
                        db.add(StoryTag(story_id=story.id, tag_id=tag.id, confidence=0.75))
                story.last_updated_at = datetime.now(timezone.utc)
                updated += 1
            db.commit()

            result = AgentResult(processed=len(stories), updated=updated)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class RankingAgent(BaseAgent):
    name = "ranking"
    LEAD_MAX_HOURS = 24.0
    MAJOR_MAX_HOURS = 48.0

    def _to_aware_utc(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _source_signal(self, db: Session, story_id: int) -> tuple[int, float]:
        rows = db.execute(
            select(Source.id, Source.authority_score)
            .join(Article, Article.source_id == Source.id)
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(StoryArticle.story_id == story_id)
        ).all()
        if not rows:
            return 0, 0.0

        authority_by_source: dict[int, float] = {}
        for source_id, authority_score in rows:
            current = authority_by_source.get(source_id)
            if current is None or authority_score > current:
                authority_by_source[source_id] = float(authority_score)
        diversity = len(authority_by_source)
        avg_authority = sum(authority_by_source.values()) / diversity if diversity else 0.0
        return diversity, avg_authority

    def _story_hours_old(self, db: Session, story: Story, now: datetime) -> float:
        latest_article = db.execute(
            select(func.max(Article.published_at))
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(StoryArticle.story_id == story.id)
        ).scalar_one_or_none()
        reference = latest_article or story.last_updated_at or story.first_seen_at
        return max(0.0, (now - self._to_aware_utc(reference)).total_seconds() / 3600.0)

    def _discussion_velocity(self, db: Session, story_id: int) -> float:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_sum = db.execute(
            select(func.coalesce(func.sum(DiscussionLink.engagement_score), 0.0)).where(
                DiscussionLink.story_id == story_id,
                DiscussionLink.captured_at >= recent_cutoff,
            )
        ).scalar_one()
        return float(recent_sum or 0.0)

    def _entity_weight(self, db: Session, story_id: int) -> float:
        avg_confidence = db.execute(
            select(func.avg(StoryTag.confidence)).where(StoryTag.story_id == story_id)
        ).scalar_one_or_none()
        return float(avg_confidence or 0.0)

    def _new_sources_velocity(self, db: Session, story_id: int) -> int:
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        count = db.execute(
            select(func.count(StoryArticle.article_id)).where(
                StoryArticle.story_id == story_id,
                StoryArticle.added_at >= recent_cutoff,
            )
        ).scalar_one()
        return int(count or 0)

    def _clamp01(self, value: float) -> float:
        return max(0.0, min(1.0, value))

    def _source_story_ids(self, db: Session, source_id: int, cutoff: datetime) -> list[int]:
        rows = db.execute(
            select(StoryArticle.story_id)
            .join(Article, Article.id == StoryArticle.article_id)
            .where(Article.source_id == source_id, Article.published_at >= cutoff)
            .distinct()
        ).all()
        return [int(row[0]) for row in rows]

    def _source_originality_score(
        self, db: Session, source_id: int, story_ids: list[int], freshness_window_hours: int = 2
    ) -> float:
        if not story_ids:
            return 0.0
        fresh_hits = 0
        tolerance = timedelta(hours=freshness_window_hours)
        for story_id in story_ids:
            earliest_any = db.execute(
                select(func.min(Article.published_at))
                .join(StoryArticle, StoryArticle.article_id == Article.id)
                .where(StoryArticle.story_id == story_id)
            ).scalar_one_or_none()
            earliest_source = db.execute(
                select(func.min(Article.published_at))
                .join(StoryArticle, StoryArticle.article_id == Article.id)
                .where(StoryArticle.story_id == story_id, Article.source_id == source_id)
            ).scalar_one_or_none()
            if not earliest_any or not earliest_source:
                continue
            if self._to_aware_utc(earliest_source) <= self._to_aware_utc(earliest_any) + tolerance:
                fresh_hits += 1
        return self._clamp01(fresh_hits / max(1, len(story_ids)))

    def _source_citation_uptake_score(self, db: Session, story_ids: list[int]) -> float:
        if not story_ids:
            return 0.0
        co_source_counts: list[float] = []
        for story_id in story_ids:
            distinct_sources = db.execute(
                select(func.count(func.distinct(Article.source_id)))
                .join(StoryArticle, StoryArticle.article_id == Article.id)
                .where(StoryArticle.story_id == story_id)
            ).scalar_one()
            co_source_counts.append(max(0.0, float(distinct_sources or 0) - 1.0))
        avg_co_sources = sum(co_source_counts) / len(co_source_counts)
        return self._clamp01(avg_co_sources / 5.0)

    def _source_correction_score(self, db: Session, source_id: int, cutoff: datetime) -> float:
        open_total = db.execute(
            select(func.count(ExceptionItem.id)).where(
                ExceptionItem.object_type == "source",
                ExceptionItem.object_id == str(source_id),
                ExceptionItem.status == "open",
                ExceptionItem.created_at >= cutoff,
            )
        ).scalar_one()
        open_high = db.execute(
            select(func.count(ExceptionItem.id)).where(
                ExceptionItem.object_type == "source",
                ExceptionItem.object_id == str(source_id),
                ExceptionItem.status == "open",
                ExceptionItem.severity == "high",
                ExceptionItem.created_at >= cutoff,
            )
        ).scalar_one()
        penalty = 0.25 * float(open_high or 0) + 0.10 * float(open_total or 0)
        return self._clamp01(1.0 - penalty)

    def _source_consistency_score(self, confidences: list[float]) -> float:
        if len(confidences) <= 1:
            return 0.8
        stdev = statistics.pstdev(confidences)
        return self._clamp01(1.0 - min(1.0, stdev))

    def _update_source_authority_scores(self, db: Session) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        sources = db.execute(select(Source).where(Source.is_active == True)).scalars().all()  # noqa: E712
        for source in sources:
            confidence_rows = db.execute(
                select(StoryArticle.cluster_confidence)
                .join(Article, Article.id == StoryArticle.article_id)
                .where(Article.source_id == source.id, Article.published_at >= cutoff)
            ).scalars().all()
            confidences = [float(value) for value in confidence_rows]
            if not confidences:
                continue

            story_ids = self._source_story_ids(db, source.id, cutoff)
            accuracy = self._clamp01(sum(confidences) / len(confidences))
            originality = self._source_originality_score(db, source.id, story_ids)
            citation_uptake = self._source_citation_uptake_score(db, story_ids)
            correction = self._source_correction_score(db, source.id, cutoff)
            consistency = self._source_consistency_score(confidences)
            observed = (
                0.35 * accuracy
                + 0.20 * originality
                + 0.20 * citation_uptake
                + 0.15 * correction
                + 0.10 * consistency
            )

            config = dict(source.crawl_config_json or {})
            prior = config.get("authority_prior")
            if not isinstance(prior, (float, int)):
                prior = float(source.authority_score)
                config["authority_prior"] = round(float(prior), 3)
            final_score = self._clamp01(0.60 * observed + 0.40 * float(prior))
            source.authority_score = round(final_score, 3)
            config["authority_v1"] = {
                "window_days": 90,
                "accuracy": round(accuracy, 3),
                "originality": round(originality, 3),
                "citation_uptake": round(citation_uptake, 3),
                "correction_behavior": round(correction, 3),
                "consistency": round(consistency, 3),
                "observed_score": round(observed, 3),
                "final_score": round(final_score, 3),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            source.crawl_config_json = config

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            self._update_source_authority_scores(db)
            stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
            now = datetime.now(timezone.utc)
            story_diversity: dict[int, int] = {}
            story_hours_old: dict[int, float] = {}
            for story in stories:
                diversity, avg_authority = self._source_signal(db, story.id)
                story_diversity[story.id] = diversity
                hours_old = self._story_hours_old(db, story, now)
                story_hours_old[story.id] = hours_old
                discussion_velocity = self._discussion_velocity(db, story.id)
                entity_weight = self._entity_weight(db, story.id)
                previous = story.importance_score
                current = score_story(
                    source_diversity=diversity,
                    authority=avg_authority,
                    hours_old=hours_old,
                    discussion_velocity=discussion_velocity,
                    entity_weight=entity_weight,
                    w_authority=settings.ranking_weight_authority,
                    w_diversity=settings.ranking_weight_diversity,
                    w_recency=settings.ranking_weight_recency,
                    w_discussion=settings.ranking_weight_discussion,
                    w_entity=settings.ranking_weight_entity,
                )
                story.importance_score = current
                story.momentum_score = momentum(previous, current, self._new_sources_velocity(db, story.id))

            ordered = sorted(stories, key=lambda s: s.importance_score, reverse=True)
            lead_assigned = False
            major_count = 0
            for story in ordered:
                diversity = story_diversity.get(story.id, 0)
                hours_old = story_hours_old.get(story.id, 0.0)
                if not lead_assigned and diversity >= settings.ranking_lead_min_source_diversity:
                    story.tier = StoryTier.lead
                    lead_assigned = True
                # Target ~10 top stories total on the homepage (1 lead + up to 9 major).
                elif major_count < 9:
                    story.tier = StoryTier.major
                    major_count += 1
                else:
                    story.tier = StoryTier.quick

                # Hard freshness gates for top tiers.
                if story.tier == StoryTier.lead and hours_old > self.LEAD_MAX_HOURS:
                    story.tier = StoryTier.major
                if story.tier == StoryTier.major and hours_old > self.MAJOR_MAX_HOURS:
                    story.tier = StoryTier.quick

                retained = apply_retention_tier(story)
                if retained == "archived":
                    story.tier = StoryTier.archived
                    story.status = StoryStatus.archived
                elif retained == "major":
                    story.tier = StoryTier.major
                elif retained == "quick":
                    story.tier = StoryTier.quick

            if ordered and not lead_assigned:
                fallback_lead = next(
                    (
                        story
                        for story in ordered
                        if story_hours_old.get(story.id, float("inf")) <= self.LEAD_MAX_HOURS
                        and story_diversity.get(story.id, 0) >= settings.ranking_lead_min_source_diversity
                        and story.tier != StoryTier.archived
                    ),
                    None,
                )
                if fallback_lead is not None:
                    fallback_lead.tier = StoryTier.lead

            db.commit()
            result = AgentResult(processed=len(stories), updated=len(stories))
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class PublishingAgent(BaseAgent):
    name = "publishing"
    MODEL_BUILDER_ENTITIES = ("OpenAI", "Anthropic", "Google DeepMind", "xAI", "Mistral", "Meta AI")
    FOUNDATION_MODEL_ENTITIES = ("GPT-4", "Claude", "Gemini", "Llama", "Grok", "Mistral Large")
    INFRA_ENTITIES = ("NVIDIA", "AWS", "Microsoft Azure", "Google Cloud", "CoreWeave", "AMD")
    APP_ENTITIES = ("ChatGPT", "Claude", "Gemini", "Perplexity", "Microsoft Copilot", "Meta AI")

    def _story_text(self, story: Story) -> str:
        bullets = " ".join(story.bullets_json or [])
        return f"{story.headline} {bullets}".lower()

    def _story_source_diversity(self, db: Session, story_id: int) -> int:
        count = db.execute(
            select(func.count(func.distinct(Source.id)))
            .join(Article, Article.source_id == Source.id)
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(StoryArticle.story_id == story_id)
        ).scalar_one()
        return int(count or 0)

    def _story_source_ids(self, db: Session, story_id: int) -> set[int]:
        rows = db.execute(
            select(func.distinct(Source.id))
            .join(Article, Article.source_id == Source.id)
            .join(StoryArticle, StoryArticle.article_id == Article.id)
            .where(StoryArticle.story_id == story_id)
        ).all()
        return {int(row[0]) for row in rows if row and row[0] is not None}

    def _latest_signal_data(self, db: Session, signal_type: str) -> dict[str, float]:
        row = db.execute(
            select(Signal).where(Signal.signal_type == signal_type).order_by(desc(Signal.observed_at)).limit(1)
        ).scalar_one_or_none()
        if not row:
            return {}
        out: dict[str, float] = {}
        for key, value in (row.value_json or {}).items():
            try:
                out[key] = float(value)
            except (TypeError, ValueError):
                continue
        return out

    def _sanitize_signal_entities(self, data: dict[str, float], allowed_entities: tuple[str, ...]) -> dict[str, float]:
        allowed = set(allowed_entities)
        return {key: value for key, value in data.items() if key in allowed}

    def _build_signal_payload_with_rows(self, db: Session, stories: list[Story], values: dict[str, float]) -> dict[str, object]:
        story_source_cache: dict[int, set[int]] = {}
        rows: list[dict[str, object]] = []
        for entity, value in sorted(values.items(), key=lambda item: item[1], reverse=True):
            normalized = entity.lower()
            sources: set[int] = set()
            for story in stories:
                text = self._story_text(story)
                if normalized not in text:
                    continue
                if story.id not in story_source_cache:
                    story_source_cache[story.id] = self._story_source_ids(db, story.id)
                sources.update(story_source_cache[story.id])
            source_count = len(sources)
            confidence = "high" if source_count >= 3 else "medium" if source_count >= 2 else "estimated"
            rows.append(
                {
                    "entity": entity,
                    "value": round(float(value), 1),
                    "confidence": confidence,
                    "source_count": source_count,
                }
            )

        payload: dict[str, object] = {key: round(float(value), 1) for key, value in values.items()}
        payload["rows"] = rows
        return payload

    def _extract_valuations_billions(self, text: str) -> list[float]:
        values: list[float] = []
        pattern = re.compile(r"\$?\s*(\d+(?:\.\d+)?)\s*(trillion|billion|million|t|b|m)\b", re.IGNORECASE)
        for amount, unit in pattern.findall(text):
            numeric = float(amount)
            unit_norm = unit.lower()
            if unit_norm in {"trillion", "t"}:
                values.append(numeric * 1000.0)
            elif unit_norm in {"billion", "b"}:
                values.append(numeric)
            else:
                values.append(numeric / 1000.0)
        return values

    def _extract_percentages(self, text: str) -> list[float]:
        values: list[float] = []
        pattern = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
        for match in pattern.findall(text):
            value = float(match)
            if 0 <= value <= 100:
                values.append(value)
        return values

    def _extract_compute_capacity_h100_eq(self, text: str) -> list[float]:
        values: list[float] = []
        pattern = re.compile(r"(\d+(?:\.\d+)?)\s*(k|m)?\s*(h100|h200|gpu|gpus)\b", re.IGNORECASE)
        for amount, magnitude, _unit in pattern.findall(text):
            numeric = float(amount)
            magnitude_norm = magnitude.lower() if magnitude else ""
            if magnitude_norm == "k":
                numeric *= 1000
            elif magnitude_norm == "m":
                numeric *= 1_000_000
            values.append(numeric)
        return values

    def _extract_mau_millions(self, text: str) -> list[float]:
        values: list[float] = []
        patterns = [
            re.compile(
                r"(\d+(?:\.\d+)?)\s*(billion|million|bn|b|mn|m)\s*(monthly active users|maus|mau)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"(\d+(?:\.\d+)?)\s*(monthly active users|maus|mau)\b",
                re.IGNORECASE,
            ),
        ]
        for pattern in patterns:
            for match in pattern.findall(text):
                amount = float(match[0])
                unit = match[1].lower() if len(match) > 2 else ""
                if unit in {"billion", "bn", "b"}:
                    values.append(amount * 1000.0)
                elif unit in {"million", "mn", "m"}:
                    values.append(amount)
                else:
                    values.append(amount)
        return values

    def _rank_entities(
        self,
        db: Session,
        stories: list[Story],
        entities: dict[str, tuple[str, ...]],
        baseline: float,
        mention_weight: float,
        diversity_weight: float,
        importance_weight: float,
        momentum_weight: float,
        cap: float,
    ) -> dict[str, float]:
        scores: dict[str, float] = {entity: baseline for entity in entities}
        for story in stories:
            text = self._story_text(story)
            matched = [entity for entity, aliases in entities.items() if any(alias in text for alias in aliases)]
            if not matched:
                continue
            diversity = self._story_source_diversity(db, story.id)
            boost = (
                mention_weight
                + diversity_weight * diversity
                + importance_weight * float(story.importance_score)
                + momentum_weight * float(story.momentum_score)
            )
            for entity in matched:
                scores[entity] += boost

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:10]
        return {name: round(min(cap, score), 1) for name, score in ranked}

    def _build_infrastructure_ranking(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "NVIDIA": ("nvidia",),
            "AWS": ("aws", "amazon web services",),
            "Microsoft Azure": ("azure", "microsoft cloud"),
            "Google Cloud": ("google cloud", "gcp"),
            "CoreWeave": ("coreweave",),
            "AMD": ("amd",),
        }
        return self._rank_entities(
            db,
            stories,
            entities,
            baseline=40.0,
            mention_weight=8.0,
            diversity_weight=2.5,
            importance_weight=18.0,
            momentum_weight=8.0,
            cap=99.0,
        )

    def _build_model_builder_valuation(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "OpenAI": ("openai",),
            "Anthropic": ("anthropic",),
            "Google DeepMind": ("deepmind",),
            "xAI": ("xai",),
            "Mistral": ("mistral",),
            "Meta AI": ("meta ai", "llama"),
        }
        baseline_vals = {
            "OpenAI": 300.0,
            "Anthropic": 60.0,
            "Google DeepMind": 50.0,
            "xAI": 45.0,
            "Mistral": 8.0,
            "Meta AI": 40.0,
        }
        valuations: dict[str, float] = {}
        for story in stories:
            text = self._story_text(story)
            if not any(word in text for word in ("valuation", "funding", "raised", "round", "investment", "tender")):
                continue
            extracted = self._extract_valuations_billions(text)
            if not extracted:
                continue
            max_value = max(extracted)
            for entity, aliases in entities.items():
                if any(alias in text for alias in aliases):
                    valuations[entity] = max(valuations.get(entity, 0.0), max_value)

        if not valuations:
            previous = self._sanitize_signal_entities(
                self._latest_signal_data(db, "funding_tracker"), self.MODEL_BUILDER_ENTITIES
            )
            if previous:
                valuations = previous
            else:
                mentions = self._rank_entities(
                    db,
                    stories,
                    entities,
                    baseline=0.0,
                    mention_weight=1.2,
                    diversity_weight=0.4,
                    importance_weight=2.0,
                    momentum_weight=0.8,
                    cap=100.0,
                )
                for entity, base in baseline_vals.items():
                    boost = min(30.0, float(mentions.get(entity, 0.0)) * 0.35)
                    valuations[entity] = round(base + boost, 1)

        for entity, base in baseline_vals.items():
            if entity in valuations:
                valuations[entity] = round(max(float(valuations[entity]), base), 1)

        ranked = sorted(valuations.items(), key=lambda item: item[1], reverse=True)[:10]
        out = {name: round(value, 1) for name, value in ranked}
        if len(out) < 3:
            for entity in self.MODEL_BUILDER_ENTITIES:
                if entity not in out:
                    out[entity] = baseline_vals[entity]
                if len(out) >= 3:
                    break
        return out

    def _build_app_mau(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "ChatGPT": ("chatgpt",),
            "Claude": ("claude.ai", "claude"),
            "Gemini": ("gemini",),
            "Perplexity": ("perplexity",),
            "Microsoft Copilot": ("copilot", "microsoft copilot"),
            "Meta AI": ("meta ai",),
        }
        baseline_mau_millions = {
            "ChatGPT": 300.0,
            "Claude": 25.0,
            "Gemini": 45.0,
            "Perplexity": 15.0,
            "Microsoft Copilot": 30.0,
            "Meta AI": 50.0,
        }
        mau: dict[str, float] = {}
        for story in stories:
            text = self._story_text(story)
            if "mau" not in text and "monthly active users" not in text and "maus" not in text:
                continue
            extracted = self._extract_mau_millions(text)
            if not extracted:
                continue
            max_value = max(extracted)
            for entity, aliases in entities.items():
                if any(alias in text for alias in aliases):
                    mau[entity] = max(mau.get(entity, 0.0), max_value)

        if not mau:
            previous = self._sanitize_signal_entities(
                self._latest_signal_data(db, "app_adoption"), self.APP_ENTITIES
            )
            if previous:
                mau = previous
            else:
                mentions = self._rank_entities(
                    db,
                    stories,
                    entities,
                    baseline=0.0,
                    mention_weight=1.0,
                    diversity_weight=0.35,
                    importance_weight=1.8,
                    momentum_weight=0.7,
                    cap=100.0,
                )
                for entity, base in baseline_mau_millions.items():
                    boost = min(20.0, float(mentions.get(entity, 0.0)) * 0.25)
                    mau[entity] = round(base + boost, 1)

        for entity, base in baseline_mau_millions.items():
            if entity in mau:
                mau[entity] = round(max(float(mau[entity]), base), 1)

        ranked = sorted(mau.items(), key=lambda item: item[1], reverse=True)[:10]
        out = {name: round(value, 1) for name, value in ranked}
        if len(out) < 4:
            for entity in self.APP_ENTITIES:
                if entity not in out:
                    out[entity] = baseline_mau_millions[entity]
                if len(out) >= 4:
                    break
        return out

    def _build_foundation_model_gpqa(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "GPT-4": ("gpt-4", "gpt4"),
            "Claude": ("claude",),
            "Gemini": ("gemini",),
            "Llama": ("llama",),
            "Grok": ("grok",),
            "Mistral Large": ("mistral large", "mistral"),
        }
        baseline_gpqa = {
            "Claude": 67.8,
            "GPT-4": 52.0,
            "Gemini": 52.0,
            "Llama": 52.0,
            "Grok": 52.0,
            "Mistral Large": 52.0,
        }
        gpqa_scores: dict[str, float] = {}
        for story in stories:
            text = self._story_text(story)
            if "gpqa" not in text:
                continue
            percentages = self._extract_percentages(text)
            if not percentages:
                continue
            best_score = max(percentages)
            for entity, aliases in entities.items():
                if any(alias in text for alias in aliases):
                    gpqa_scores[entity] = max(gpqa_scores.get(entity, 0.0), best_score)

        if not gpqa_scores:
            previous = self._sanitize_signal_entities(
                self._latest_signal_data(db, "model_activity"), self.FOUNDATION_MODEL_ENTITIES
            )
            if previous:
                gpqa_scores = previous
            else:
                mentions = self._rank_entities(
                    db,
                    stories,
                    entities,
                    baseline=0.0,
                    mention_weight=1.0,
                    diversity_weight=0.25,
                    importance_weight=1.5,
                    momentum_weight=0.6,
                    cap=20.0,
                )
                for entity, base in baseline_gpqa.items():
                    boost = min(3.0, float(mentions.get(entity, 0.0)) * 0.05)
                    gpqa_scores[entity] = round(min(95.0, base + boost), 1)

        ranked = sorted(gpqa_scores.items(), key=lambda item: item[1], reverse=True)[:10]
        out = {name: round(value, 1) for name, value in ranked}
        if len(out) < 4:
            for entity in self.FOUNDATION_MODEL_ENTITIES:
                if entity not in out:
                    out[entity] = baseline_gpqa.get(entity, 52.0)
                if len(out) >= 4:
                    break
        return out

    def _build_infrastructure_compute_capacity(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "NVIDIA": ("nvidia",),
            "AWS": ("aws", "amazon web services"),
            "Microsoft Azure": ("azure", "microsoft cloud"),
            "Google Cloud": ("google cloud", "gcp"),
            "CoreWeave": ("coreweave",),
            "AMD": ("amd",),
        }
        capacities: dict[str, float] = {}
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)
        for story in stories:
            if to_aware_utc(story.first_seen_at) < cutoff:
                continue
            text = self._story_text(story)
            if not any(word in text for word in ("gpu", "h100", "h200", "capacity", "cluster", "datacenter")):
                continue
            extracted = self._extract_compute_capacity_h100_eq(text)
            if not extracted:
                continue
            max_value = max(extracted)
            for entity, aliases in entities.items():
                if any(alias in text for alias in aliases):
                    capacities[entity] = capacities.get(entity, 0.0) + max_value

        if not capacities:
            previous = self._sanitize_signal_entities(
                self._latest_signal_data(db, "trending_repos"), self.INFRA_ENTITIES
            )
            if previous:
                capacities = previous
            else:
                capacities = self._build_infrastructure_ranking(db, stories)
        if len(capacities) < 3:
            defaults = {
                "NVIDIA": 40.0,
                "AWS": 40.0,
                "Microsoft Azure": 40.0,
                "Google Cloud": 40.0,
                "CoreWeave": 40.0,
                "AMD": 40.0,
            }
            for entity in self.INFRA_ENTITIES:
                capacities.setdefault(entity, defaults[entity])
                if len(capacities) >= 3:
                    break

        ranked = sorted(capacities.items(), key=lambda item: item[1], reverse=True)[:10]
        return {name: round(value, 1) for name, value in ranked}

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            stories = db.execute(
                select(Story)
                .where(Story.status == StoryStatus.active)
                .order_by(desc(Story.importance_score), desc(Story.last_updated_at))
                .limit(30)
            ).scalars().all()
            lead = next((s for s in stories if s.tier == StoryTier.lead), None)
            snapshot = FeedSnapshot(lead_story_id=lead.id if lead else None, metadata_json={"mode": "agent-run"})
            db.add(snapshot)
            db.flush()

            for position, story in enumerate(stories, start=1):
                if story.tier == StoryTier.archived:
                    continue
                section = "All"
                db.add(
                    FeedSnapshotItem(
                        snapshot_id=snapshot.id,
                        story_id=story.id,
                        section=section,
                        tier=story.tier,
                        position=position,
                    )
                )
                story.last_published_at = datetime.now(timezone.utc)

            infra = self._build_infrastructure_compute_capacity(db, stories)
            valuations = self._build_model_builder_valuation(db, stories)
            models = self._build_foundation_model_gpqa(db, stories)
            mau = self._build_app_mau(db, stories)
            signals = [
                Signal(
                    signal_type="app_adoption",
                    title="Monthly Active Users",
                    value_json=self._build_signal_payload_with_rows(db, stories, mau),
                    rank=1,
                ),
                Signal(
                    signal_type="model_activity",
                    title="Foundation Models",
                    value_json=self._build_signal_payload_with_rows(db, stories, models),
                    rank=2,
                ),
                Signal(
                    signal_type="funding_tracker",
                    title="Model Builders",
                    value_json=self._build_signal_payload_with_rows(db, stories, valuations),
                    rank=3,
                ),
                Signal(
                    signal_type="trending_repos",
                    title="Infrastructure Leaders",
                    value_json=self._build_signal_payload_with_rows(db, stories, infra),
                    rank=4,
                ),
            ]
            for signal in signals:
                db.add(signal)

            db.commit()
            result = AgentResult(processed=len(stories), created=1)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class MonitoringQaAgent(BaseAgent):
    name = "monitoring_qa"

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
            created = 0
            for story in stories:
                bullets = story.bullets_json or []
                expected_max = target_bullet_count(story.tier, story.importance_score)
                if not (1 <= len(bullets) <= expected_max):
                    db.add(
                        ExceptionItem(
                            agent_name=self.name,
                            object_type="story",
                            object_id=str(story.id),
                            reason="Story bullet count outside expected range",
                            severity="high",
                            payload_json={"bullets": bullets, "expected_max": expected_max},
                        )
                    )
                    created += 1
            db.commit()
            result = AgentResult(processed=len(stories), created=created)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class SelfHealAgent(BaseAgent):
    name = "self_heal"

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            resolved = auto_resolve_stale_low_exceptions(db)
            result = AgentResult(processed=resolved, updated=resolved)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class PolicyTuningAgent(BaseAgent):
    name = "policy_tuning"

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            controls = tune_agent_controls(db)
            set_memory(
                db,
                "policy_tuning_last_result",
                {
                    "value": controls,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "updated_by": self.name,
                },
            )
            db.commit()
            result = AgentResult(processed=1, updated=1)
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


PIPELINE = {
    "crawler": CrawlerAgent(),
    "normalization": NormalizationAgent(),
    "embedding": EmbeddingAgent(),
    "clustering": ClusteringAgent(),
    "merge_clusters": MergeClustersAgent(),
    "summarization_tagging": SummarizationTaggingAgent(),
    "ranking": RankingAgent(),
    "monitoring_qa": MonitoringQaAgent(),
    "self_heal": SelfHealAgent(),
    "policy_tuning": PolicyTuningAgent(),
    "publishing": PublishingAgent(),
}


def reconcile_stale_running_agent_runs(db: Session, stale_minutes: int = 15) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    rows = db.execute(
        select(AgentRun).where(
            AgentRun.status == RunStatus.running,
            AgentRun.agent_name.in_(list(PIPELINE.keys())),
            AgentRun.started_at < cutoff,
        )
    ).scalars().all()
    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    for run in rows:
        run.status = RunStatus.failed
        run.ended_at = now
        run.error_text = "Marked stale after exceeding runtime window."
        db.add(run)
    db.commit()
    return len(rows)


def has_recent_running_pipeline_activity(db: Session, active_window_minutes: int = 20) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=active_window_minutes)
    count = db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.status == RunStatus.running,
            AgentRun.agent_name.in_(list(PIPELINE.keys())),
            AgentRun.started_at >= cutoff,
        )
    ).scalar_one()
    return int(count or 0) > 0


def run_pipeline_steps(db: Session, ordered: list[str]) -> dict[str, dict]:
    reconcile_stale_running_agent_runs(db)
    results: dict[str, dict] = {}

    for name in ordered:
        agent = PIPELINE[name]
        result = agent.run(db)
        results[name] = {"processed": result.processed, "created": result.created, "updated": result.updated}

    return results


def run_pipeline(db: Session) -> dict[str, dict]:
    ordered = [
        "crawler",
        "normalization",
        "embedding",
        "clustering",
        "merge_clusters",
        "summarization_tagging",
        "ranking",
        "monitoring_qa",
        "self_heal",
        "policy_tuning",
        "publishing",
    ]
    return run_pipeline_steps(db, ordered)


def run_single_agent(db: Session, agent_name: str) -> dict:
    if agent_name not in PIPELINE:
        raise ValueError(f"Unknown agent: {agent_name}")
    reconcile_stale_running_agent_runs(db)
    result = PIPELINE[agent_name].run(db)
    return {"agent": agent_name, "processed": result.processed, "created": result.created, "updated": result.updated}
