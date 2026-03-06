from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline
from app.db.base import Base
from app.models.news import FeedSnapshot, Source, SourceState, SourceType, Story, StoryStatus


def test_pipeline_e2e_smoke() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Source(
                name="SmokeSource",
                domain="smoke.example.com",
                type=SourceType.news,
                authority_score=0.8,
                state=SourceState.trusted,
                crawl_config_json={"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": []},
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        results = run_pipeline(db)
        assert "crawler" in results
        assert "publishing" in results

        snapshot = db.execute(select(FeedSnapshot).order_by(FeedSnapshot.id.desc())).scalar_one_or_none()
        assert snapshot is not None

        active_stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
        assert len(active_stories) >= 1
