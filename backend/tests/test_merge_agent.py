from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import MergeClustersAgent
from app.db.base import Base
from app.models.news import (
    Article,
    ArticleEmbedding,
    Source,
    SourceState,
    SourceType,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTier,
)


def test_merge_clusters_agent_archives_duplicate_story(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source = Source(
            name="TestSource",
            domain="example.com",
            type=SourceType.news,
            authority_score=0.8,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        db.add(source)
        db.flush()

        article_a = Article(
            source_id=source.id,
            canonical_url="https://example.com/a",
            title="OpenAI launches agent sdk",
            content_text="OpenAI launches an agent SDK for developers",
            snippet="OpenAI launches an agent SDK",
            published_at=datetime.now(timezone.utc),
            content_hash="a" * 64,
            language="en",
        )
        article_b = Article(
            source_id=source.id,
            canonical_url="https://example.com/b",
            title="OpenAI ships new agent SDK",
            content_text="OpenAI ships a new SDK for autonomous agents",
            snippet="OpenAI ships new agent SDK",
            published_at=datetime.now(timezone.utc),
            content_hash="b" * 64,
            language="en",
        )
        db.add_all([article_a, article_b])
        db.flush()

        story_a = Story(
            slug="openai-agent-sdk",
            headline="OpenAI launches agent SDK",
            bullets_json=["b1", "b2", "b3"],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            importance_score=0.6,
            momentum_score=0.3,
        )
        story_b = Story(
            slug="openai-new-agent-sdk",
            headline="OpenAI ships new agent SDK",
            bullets_json=["c1", "c2", "c3"],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            importance_score=0.5,
            momentum_score=0.2,
        )
        db.add_all([story_a, story_b])
        db.flush()

        db.add_all(
            [
                StoryArticle(story_id=story_a.id, article_id=article_a.id, cluster_confidence=0.9, is_primary=True),
                StoryArticle(story_id=story_b.id, article_id=article_b.id, cluster_confidence=0.9, is_primary=True),
                ArticleEmbedding(article_id=article_a.id, embedding=[0.9, 0.1, 0.0], model_name="test"),
                ArticleEmbedding(article_id=article_b.id, embedding=[0.88, 0.12, 0.0], model_name="test"),
            ]
        )
        db.commit()

        from app.core.config import settings

        monkeypatch.setattr(settings, "story_merge_min_confidence", 0.4)
        monkeypatch.setattr(settings, "story_merge_window_hours", 240)
        monkeypatch.setattr(settings, "story_merge_max_candidates", 10)

        agent = MergeClustersAgent()
        result = agent.run(db)
        assert result.updated >= 1

        stories = db.execute(select(Story).order_by(Story.id)).scalars().all()
        archived_count = sum(1 for story in stories if story.status == StoryStatus.archived)
        assert archived_count == 1

        active_story = next(story for story in stories if story.status == StoryStatus.active)
        active_links = db.execute(select(StoryArticle).where(StoryArticle.story_id == active_story.id)).scalars().all()
        assert len(active_links) == 2
