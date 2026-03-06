from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.news import AgentRun, ExceptionItem, ExceptionStatus, FeedSnapshot, RunStatus, Story, StoryArticle, StoryStatus
from app.schemas.news import OpsPolicyEvaluation, OpsQualityMetrics


def _to_aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def collect_ops_quality_metrics(db: Session) -> OpsQualityMetrics:
    now = datetime.now(timezone.utc)
    last_publish = db.execute(select(func.max(FeedSnapshot.published_at))).scalar_one_or_none()
    last_publish_aware = _to_aware_utc(last_publish)

    open_exceptions_total = db.execute(
        select(func.count(ExceptionItem.id)).where(ExceptionItem.status == ExceptionStatus.open)
    ).scalar_one()
    open_exceptions_high = db.execute(
        select(func.count(ExceptionItem.id)).where(
            ExceptionItem.status == ExceptionStatus.open,
            ExceptionItem.severity == "high",
        )
    ).scalar_one()

    active_stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
    bullet_ok = sum(1 for story in active_stories if len(story.bullets_json or []) == 3)
    bullet_compliance = (bullet_ok / len(active_stories)) if active_stories else 1.0

    cluster_avg = db.execute(select(func.avg(StoryArticle.cluster_confidence))).scalar_one_or_none()
    cluster_avg_val = float(cluster_avg or 0.0)
    cluster_low_count = db.execute(
        select(func.count(StoryArticle.article_id)).where(StoryArticle.cluster_confidence < 0.5)
    ).scalar_one()

    window_24h = now - timedelta(hours=24)
    merged_story_count_24h = db.execute(
        select(func.count(Story.id)).where(
            Story.status == StoryStatus.archived,
            Story.last_updated_at >= window_24h,
        )
    ).scalar_one()

    failed_runs_24h = db.execute(
        select(func.count(AgentRun.id)).where(
            AgentRun.status == RunStatus.failed,
            AgentRun.started_at >= window_24h,
        )
    ).scalar_one()

    last_runs = db.execute(
        select(AgentRun).order_by(desc(AgentRun.started_at)).limit(200)
    ).scalars().all()
    agent_last_run: dict[str, dict] = {}
    for run in last_runs:
        if run.agent_name in agent_last_run:
            continue
        started = _to_aware_utc(run.started_at)
        agent_last_run[run.agent_name] = {
            "started_at": started.isoformat() if started else None,
            "status": run.status.value,
            "processed": (run.metrics_json or {}).get("processed", 0),
        }

    staleness_minutes = None
    if last_publish_aware:
        staleness_minutes = (now - last_publish_aware).total_seconds() / 60

    return OpsQualityMetrics(
        generated_at=now,
        publish_staleness_minutes=staleness_minutes,
        open_exceptions_total=int(open_exceptions_total or 0),
        open_exceptions_high=int(open_exceptions_high or 0),
        bullet_compliance_rate=float(bullet_compliance),
        cluster_confidence_avg=cluster_avg_val,
        cluster_confidence_low_count=int(cluster_low_count or 0),
        merged_story_count_24h=int(merged_story_count_24h or 0),
        failed_agent_runs_24h=int(failed_runs_24h or 0),
        active_story_count=len(active_stories),
        agent_last_run=agent_last_run,
    )


def evaluate_ops_policy(db: Session) -> OpsPolicyEvaluation:
    metrics = collect_ops_quality_metrics(db)
    blockers: list[str] = []

    if metrics.publish_staleness_minutes is None:
        blockers.append("No publish snapshot available")
    elif metrics.publish_staleness_minutes > settings.ops_max_publish_staleness_minutes:
        blockers.append(
            f"Publish staleness too high ({metrics.publish_staleness_minutes:.1f}m > {settings.ops_max_publish_staleness_minutes}m)"
        )

    if metrics.open_exceptions_high > settings.ops_max_open_high_exceptions:
        blockers.append(
            f"High severity exceptions exceed limit ({metrics.open_exceptions_high} > {settings.ops_max_open_high_exceptions})"
        )

    if metrics.bullet_compliance_rate < settings.ops_min_bullet_compliance:
        blockers.append(
            f"Bullet compliance too low ({metrics.bullet_compliance_rate:.2f} < {settings.ops_min_bullet_compliance:.2f})"
        )

    status = "pass" if not blockers else "hold"
    return OpsPolicyEvaluation(status=status, blocking_reasons=blockers, metrics=metrics)


def evaluate_prepublish_policy(db: Session) -> OpsPolicyEvaluation:
    metrics = collect_ops_quality_metrics(db)
    blockers: list[str] = []

    if metrics.open_exceptions_high > settings.ops_max_open_high_exceptions:
        blockers.append(
            f"High severity exceptions exceed limit ({metrics.open_exceptions_high} > {settings.ops_max_open_high_exceptions})"
        )

    if metrics.bullet_compliance_rate < settings.ops_min_bullet_compliance:
        blockers.append(
            f"Bullet compliance too low ({metrics.bullet_compliance_rate:.2f} < {settings.ops_min_bullet_compliance:.2f})"
        )

    if metrics.cluster_confidence_avg < 0.5 and metrics.active_story_count > 0:
        blockers.append(
            f"Average cluster confidence too low ({metrics.cluster_confidence_avg:.2f} < 0.50)"
        )

    status = "pass" if not blockers else "hold"
    return OpsPolicyEvaluation(status=status, blocking_reasons=blockers, metrics=metrics)
