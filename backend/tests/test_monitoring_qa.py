from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import run_single_agent
from app.db.base import Base
from app.models.news import ExceptionItem, ExceptionStatus, Story, StoryStatus, StoryTier


def test_monitoring_qa_creates_single_medium_exception_per_story() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        story = Story(
            slug="s1",
            headline="Bad bullets",
            bullets_json=[],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            importance_score=0.3,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add(story)
        db.commit()

        run_single_agent(db, "monitoring_qa")
        run_single_agent(db, "monitoring_qa")

        items = db.execute(
            select(ExceptionItem).where(
                ExceptionItem.agent_name == "monitoring_qa",
                ExceptionItem.object_id == str(story.id),
                ExceptionItem.reason == "Story bullet count outside expected range",
                ExceptionItem.status == ExceptionStatus.open,
            )
        ).scalars().all()
        assert len(items) == 1
        assert items[0].severity == "medium"


def test_monitoring_qa_resolves_exception_when_story_is_compliant() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        story = Story(
            slug="s2",
            headline="Recovering bullets",
            bullets_json=[],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            importance_score=0.2,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add(story)
        db.commit()

        run_single_agent(db, "monitoring_qa")

        story.bullets_json = ["Now valid"]
        db.add(story)
        db.commit()
        run_single_agent(db, "monitoring_qa")

        open_items = db.execute(
            select(ExceptionItem).where(
                ExceptionItem.agent_name == "monitoring_qa",
                ExceptionItem.object_id == str(story.id),
                ExceptionItem.reason == "Story bullet count outside expected range",
                ExceptionItem.status == ExceptionStatus.open,
            )
        ).scalars().all()
        assert open_items == []

        resolved = db.execute(
            select(ExceptionItem).where(
                ExceptionItem.agent_name == "monitoring_qa",
                ExceptionItem.object_id == str(story.id),
                ExceptionItem.reason == "Story bullet count outside expected range",
                ExceptionItem.status == ExceptionStatus.resolved,
            )
        ).scalars().all()
        assert len(resolved) >= 1
        assert resolved[0].resolved_at is not None
