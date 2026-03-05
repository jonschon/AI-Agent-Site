from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from slugify import slugify
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.news import (
    AgentRun,
    Article,
    ArticleEmbedding,
    ExceptionItem,
    FeedSnapshot,
    FeedSnapshotItem,
    RawArticle,
    RunStatus,
    Signal,
    Source,
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
from app.services.crawler import build_synthetic_entry, fetch_feed_entries
from app.services.model_gateway import generate_embedding, infer_tags, summarize_story
from app.services.scoring import apply_retention_tier, momentum, score_story


@dataclass
class AgentResult:
    processed: int
    created: int = 0
    updated: int = 0


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

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            sources = db.execute(select(Source).where(Source.is_active == True)).scalars().all()  # noqa: E712
            created = 0
            for source in sources:
                entries = fetch_feed_entries(source, limit=15)
                if not entries:
                    entries = [build_synthetic_entry(source)]

                for entry in entries:
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
            db.commit()
            result = AgentResult(processed=len(sources), created=created)
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
        self, db: Session, article: Article, article_embedding: list[float]
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

        if best_confidence < settings.clustering_min_confidence:
            return None, best_confidence
        return best_story, best_confidence

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            articles = db.execute(select(Article).order_by(desc(Article.published_at)).limit(40)).scalars().all()
            created = 0
            updated = 0
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

                story, confidence = self._find_candidate_story(db, article, article_embedding)

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


class SummarizationTaggingAgent(BaseAgent):
    name = "summarization_tagging"

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
                headline, bullets = summarize_story(headline_seed, snippets)
                story.headline = headline
                story.bullets_json = bullets

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

    def run(self, db: Session) -> AgentResult:
        run = self._start_run(db)
        try:
            stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
            now = datetime.now(timezone.utc)
            for story in stories:
                source_count = db.execute(
                    select(StoryArticle).where(StoryArticle.story_id == story.id)
                ).scalars().all()
                diversity = len(source_count)
                hours_old = (now - story.first_seen_at).total_seconds() / 3600
                previous = story.importance_score
                current = score_story(diversity, authority=0.7, hours_old=hours_old, discussion_velocity=10)
                story.importance_score = current
                story.momentum_score = momentum(previous, current, max(0, diversity - 1))

            ordered = sorted(stories, key=lambda s: s.importance_score, reverse=True)
            for idx, story in enumerate(ordered):
                if idx == 0:
                    story.tier = StoryTier.lead
                elif idx < 6:
                    story.tier = StoryTier.major
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

            db.commit()
            result = AgentResult(processed=len(stories), updated=len(stories))
            self._finish_run(db, run, result)
            return result
        except Exception as exc:
            self._fail_run(db, run, exc)
            raise


class PublishingAgent(BaseAgent):
    name = "publishing"

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

            signals = [
                Signal(signal_type="model_activity", title="Model Activity", value_json={"items": 3}, rank=1),
                Signal(signal_type="trending_repos", title="Trending AI Repos", value_json={"items": 5}, rank=2),
                Signal(signal_type="funding_tracker", title="AI Funding Tracker", value_json={"items": 2}, rank=3),
                Signal(signal_type="research_papers", title="New Research Papers", value_json={"items": 4}, rank=4),
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
                if len(bullets) != 3:
                    db.add(
                        ExceptionItem(
                            agent_name=self.name,
                            object_type="story",
                            object_id=str(story.id),
                            reason="Story must have exactly 3 bullets",
                            severity="high",
                            payload_json={"bullets": bullets},
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


PIPELINE = {
    "crawler": CrawlerAgent(),
    "normalization": NormalizationAgent(),
    "embedding": EmbeddingAgent(),
    "clustering": ClusteringAgent(),
    "summarization_tagging": SummarizationTaggingAgent(),
    "ranking": RankingAgent(),
    "publishing": PublishingAgent(),
    "monitoring_qa": MonitoringQaAgent(),
}


def run_pipeline(db: Session) -> dict[str, dict]:
    results: dict[str, dict] = {}
    ordered = [
        "crawler",
        "normalization",
        "embedding",
        "clustering",
        "summarization_tagging",
        "ranking",
        "publishing",
        "monitoring_qa",
    ]

    for name in ordered:
        agent = PIPELINE[name]
        result = agent.run(db)
        results[name] = {"processed": result.processed, "created": result.created, "updated": result.updated}

    return results


def run_single_agent(db: Session, agent_name: str) -> dict:
    if agent_name not in PIPELINE:
        raise ValueError(f"Unknown agent: {agent_name}")
    result = PIPELINE[agent_name].run(db)
    return {"agent": agent_name, "processed": result.processed, "created": result.created, "updated": result.updated}
