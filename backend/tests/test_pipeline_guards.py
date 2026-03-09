from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.pipeline import (
    has_recent_running_pipeline_activity,
    reconcile_stale_running_agent_runs,
)
from app.db.base import Base
from app.models.news import AgentRun, RunStatus


def test_reconcile_stale_running_agent_runs_marks_failed() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            AgentRun(
                agent_name="ranking",
                status=RunStatus.running,
                started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        db.commit()

        updated = reconcile_stale_running_agent_runs(db, stale_minutes=30)
        assert updated == 1

        row = db.query(AgentRun).first()
        assert row is not None
        assert row.status == RunStatus.failed
        assert row.ended_at is not None


def test_has_recent_running_pipeline_activity_detects_active_run() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            AgentRun(
                agent_name="clustering",
                status=RunStatus.running,
                started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            )
        )
        db.commit()

        assert has_recent_running_pipeline_activity(db, active_window_minutes=20) is True
