from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import RankingAgent
from app.db.base import Base
from app.models.news import (
    Article,
    ExceptionItem,
    ExceptionStatus,
    Source,
    SourceState,
    SourceType,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTier,
)


def test_ranking_lead_requires_min_source_diversity(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source_a = Source(
            name="HighAuthority",
            domain="ha.example.com",
            type=SourceType.news,
            authority_score=1.0,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        source_b = Source(
            name="SourceB",
            domain="b.example.com",
            type=SourceType.news,
            authority_score=0.7,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        source_c = Source(
            name="SourceC",
            domain="c.example.com",
            type=SourceType.news,
            authority_score=0.7,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        db.add_all([source_a, source_b, source_c])
        db.flush()

        story_one = Story(
            slug="single-source-story",
            headline="Single source breaking AI story",
            bullets_json=["x", "y", "z"],
            status=StoryStatus.active,
            tier=StoryTier.quick,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        story_two = Story(
            slug="multi-source-story",
            headline="Multi source AI development",
            bullets_json=["a", "b", "c"],
            status=StoryStatus.active,
            tier=StoryTier.quick,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add_all([story_one, story_two])
        db.flush()

        article_1 = Article(
            source_id=source_a.id,
            canonical_url="https://ha.example.com/1",
            title="Single source title",
            content_text="text",
            snippet="text",
            published_at=datetime.now(timezone.utc),
            content_hash="1" * 64,
            language="en",
        )
        article_2 = Article(
            source_id=source_b.id,
            canonical_url="https://b.example.com/2",
            title="multi source title 1",
            content_text="text",
            snippet="text",
            published_at=datetime.now(timezone.utc),
            content_hash="2" * 64,
            language="en",
        )
        article_3 = Article(
            source_id=source_c.id,
            canonical_url="https://c.example.com/3",
            title="multi source title 2",
            content_text="text",
            snippet="text",
            published_at=datetime.now(timezone.utc),
            content_hash="3" * 64,
            language="en",
        )
        db.add_all([article_1, article_2, article_3])
        db.flush()

        db.add_all(
            [
                StoryArticle(story_id=story_one.id, article_id=article_1.id, cluster_confidence=0.9),
                StoryArticle(story_id=story_two.id, article_id=article_2.id, cluster_confidence=0.9),
                StoryArticle(story_id=story_two.id, article_id=article_3.id, cluster_confidence=0.9),
            ]
        )
        db.commit()

        from app.core.config import settings

        monkeypatch.setattr(settings, "ranking_lead_min_source_diversity", 2)

        result = RankingAgent().run(db)
        assert result.updated == 2

        refreshed = db.execute(select(Story).order_by(Story.id)).scalars().all()
        lead = next(story for story in refreshed if story.tier == StoryTier.lead)
        assert lead.id == story_two.id


def test_ranking_updates_source_authority_with_observed_components() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source_good = Source(
            name="GoodSource",
            domain="good.example.com",
            type=SourceType.news,
            authority_score=0.5,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        source_weak = Source(
            name="WeakSource",
            domain="weak.example.com",
            type=SourceType.news,
            authority_score=0.5,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        db.add_all([source_good, source_weak])
        db.flush()

        story_good = Story(
            slug="story-good",
            headline="Good source AI update",
            bullets_json=["a", "b", "c"],
            status=StoryStatus.active,
            tier=StoryTier.quick,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        story_weak = Story(
            slug="story-weak",
            headline="Weak source AI update",
            bullets_json=["a", "b", "c"],
            status=StoryStatus.active,
            tier=StoryTier.quick,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add_all([story_good, story_weak])
        db.flush()

        good_article = Article(
            source_id=source_good.id,
            canonical_url="https://good.example.com/1",
            title="Good",
            content_text="Good",
            snippet="Good",
            published_at=datetime.now(timezone.utc),
            content_hash="4" * 64,
            language="en",
        )
        weak_article = Article(
            source_id=source_weak.id,
            canonical_url="https://weak.example.com/1",
            title="Weak",
            content_text="Weak",
            snippet="Weak",
            published_at=datetime.now(timezone.utc),
            content_hash="5" * 64,
            language="en",
        )
        db.add_all([good_article, weak_article])
        db.flush()

        db.add_all(
            [
                StoryArticle(story_id=story_good.id, article_id=good_article.id, cluster_confidence=0.95),
                StoryArticle(story_id=story_weak.id, article_id=weak_article.id, cluster_confidence=0.25),
                ExceptionItem(
                    agent_name="crawler",
                    object_type="source",
                    object_id=str(source_weak.id),
                    reason="Repeated crawl failures",
                    severity="high",
                    status=ExceptionStatus.open,
                ),
            ]
        )
        db.commit()

        RankingAgent().run(db)

        refreshed_sources = db.execute(select(Source).order_by(Source.id)).scalars().all()
        good_refreshed = refreshed_sources[0]
        weak_refreshed = refreshed_sources[1]
        assert good_refreshed.authority_score > weak_refreshed.authority_score
        assert "authority_prior" in (good_refreshed.crawl_config_json or {})
        assert "authority_v1" in (good_refreshed.crawl_config_json or {})
