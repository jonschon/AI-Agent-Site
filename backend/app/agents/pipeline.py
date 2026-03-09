from __future__ import annotations

import hashlib
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

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
            now = datetime.now(timezone.utc)
            story_diversity: dict[int, int] = {}
            for story in stories:
                diversity, avg_authority = self._source_signal(db, story.id)
                story_diversity[story.id] = diversity
                hours_old = (now - self._to_aware_utc(story.first_seen_at)).total_seconds() / 3600
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
                if not lead_assigned and diversity >= settings.ranking_lead_min_source_diversity:
                    story.tier = StoryTier.lead
                    lead_assigned = True
                elif major_count < 5:
                    story.tier = StoryTier.major
                    major_count += 1
                else:
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
                ordered[0].tier = StoryTier.lead

            db.commit()
            result = AgentResult(processed=len(stories), updated=len(stories))
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class PublishingAgent(BaseAgent):
    name = "publishing"

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
            previous = self._latest_signal_data(db, "funding_tracker")
            if previous:
                valuations = previous

        if not valuations:
            coverage_proxy = self._rank_entities(
                db,
                stories,
                entities,
                baseline=15.0,
                mention_weight=6.0,
                diversity_weight=1.8,
                importance_weight=14.0,
                momentum_weight=6.0,
                cap=120.0,
            )
            valuations = coverage_proxy

        ranked = sorted(valuations.items(), key=lambda item: item[1], reverse=True)[:10]
        return {name: round(value, 1) for name, value in ranked}

    def _build_foundation_model_ranking(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "GPT-4": ("gpt-4", "gpt4", "openai model"),
            "Claude": ("claude",),
            "Gemini": ("gemini",),
            "Llama": ("llama",),
            "Grok": ("grok",),
            "Mistral Large": ("mistral large", "mistral"),
        }
        return self._rank_entities(
            db,
            stories,
            entities,
            baseline=52.0,
            mention_weight=6.0,
            diversity_weight=2.2,
            importance_weight=14.0,
            momentum_weight=7.0,
            cap=98.0,
        )

    def _build_application_ranking(self, db: Session, stories: list[Story]) -> dict[str, float]:
        entities = {
            "ChatGPT": ("chatgpt",),
            "Claude.ai": ("claude.ai", "claude app"),
            "Perplexity": ("perplexity",),
            "GitHub Copilot": ("copilot",),
            "Cursor": ("cursor",),
            "Midjourney": ("midjourney",),
        }
        return self._rank_entities(
            db,
            stories,
            entities,
            baseline=8.0,
            mention_weight=4.0,
            diversity_weight=1.4,
            importance_weight=7.0,
            momentum_weight=4.0,
            cap=120.0,
        )

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

            infra = self._build_infrastructure_ranking(db, stories)
            valuations = self._build_model_builder_valuation(db, stories)
            models = self._build_foundation_model_ranking(db, stories)
            apps = self._build_application_ranking(db, stories)
            signals = [
                Signal(signal_type="trending_repos", title="Infrastructure Leaders", value_json=infra, rank=1),
                Signal(signal_type="funding_tracker", title="Model Builders", value_json=valuations, rank=2),
                Signal(signal_type="model_activity", title="Foundation Models", value_json=models, rank=3),
                Signal(signal_type="research_papers", title="Applications", value_json=apps, rank=4),
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


def run_pipeline_steps(db: Session, ordered: list[str]) -> dict[str, dict]:
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
    result = PIPELINE[agent_name].run(db)
    return {"agent": agent_name, "processed": result.processed, "created": result.created, "updated": result.updated}
