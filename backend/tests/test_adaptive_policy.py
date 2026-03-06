from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.news import (
    AgentMemory,
    Article,
    Source,
    SourceState,
    SourceType,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTier,
)
from app.services.adaptive_policy_service import tune_agent_controls
from app.services.memory_service import get_float_control, set_memory


def test_tune_agent_controls_adjusts_cluster_threshold_up() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source = Source(
            name="S",
            domain="s.example.com",
            type=SourceType.news,
            authority_score=0.7,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
        )
        db.add(source)
        db.flush()

        article = Article(
            source_id=source.id,
            canonical_url="https://s.example.com/a",
            title="A",
            content_text="A",
            snippet="A",
            published_at=datetime.now(timezone.utc),
            content_hash="a" * 64,
            language="en",
        )
        db.add(article)
        db.flush()

        story = Story(
            slug="s1",
            headline="Story",
            bullets_json=["a", "b", "c"],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add(story)
        db.flush()
        db.add(StoryArticle(story_id=story.id, article_id=article.id, cluster_confidence=0.2))
        db.commit()

        set_memory(db, "clustering_min_confidence", {"value": 0.58})
        db.commit()

        controls = tune_agent_controls(db)
        assert controls["clustering_min_confidence"] >= 0.58

        stored = get_float_control(db, "clustering_min_confidence", 0.0)
        assert stored >= 0.58


def test_tune_agent_controls_sets_crawl_mode() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        controls = tune_agent_controls(db)
        assert controls["crawl_aggressiveness"] in {"normal", "aggressive", "conservative"}

        rows = db.execute(select(AgentMemory)).scalars().all()
        assert any(row.key == "crawl_aggressiveness" for row in rows)
