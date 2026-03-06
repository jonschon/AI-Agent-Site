from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.news import (
    AgentRun,
    ExceptionItem,
    ExceptionStatus,
    FeedSnapshot,
    RunStatus,
    Story,
    StoryStatus,
    StoryTier,
)
from app.services.ops_service import collect_ops_quality_metrics, evaluate_ops_policy
from app.services.ops_service import evaluate_prepublish_policy


def test_collect_ops_quality_metrics() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            FeedSnapshot(
                published_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                version="v1",
                metadata_json={},
            )
        )
        db.add(
            Story(
                slug="s1",
                headline="AI story",
                bullets_json=["a", "b", "c"],
                tier=StoryTier.quick,
                status=StoryStatus.active,
                first_seen_at=datetime.now(timezone.utc),
                last_updated_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            AgentRun(
                agent_name="crawler",
                status=RunStatus.success,
                metrics_json={"processed": 10},
                started_at=datetime.now(timezone.utc),
            )
        )
        db.add(
            ExceptionItem(
                agent_name="monitoring_qa",
                object_type="story",
                object_id="1",
                reason="bad bullets",
                severity="high",
                status=ExceptionStatus.open,
            )
        )
        db.commit()

        metrics = collect_ops_quality_metrics(db)
        assert metrics.publish_staleness_minutes is not None
        assert metrics.open_exceptions_total == 1
        assert metrics.open_exceptions_high == 1
        assert metrics.active_story_count == 1
        assert metrics.bullet_compliance_rate == 1.0


def test_policy_eval_holds_when_no_publish() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        policy = evaluate_ops_policy(db)
        assert policy.status == "hold"
        assert any("No publish snapshot" in reason for reason in policy.blocking_reasons)


def test_prepublish_policy_holds_on_high_exceptions(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            ExceptionItem(
                agent_name="monitoring_qa",
                object_type="story",
                object_id="1",
                reason="bad bullets",
                severity="high",
                status=ExceptionStatus.open,
            )
        )
        db.commit()

        from app.core.config import settings

        monkeypatch.setattr(settings, "ops_max_open_high_exceptions", 0)
        policy = evaluate_prepublish_policy(db)
        assert policy.status == "hold"
        assert any("High severity exceptions exceed limit" in reason for reason in policy.blocking_reasons)
