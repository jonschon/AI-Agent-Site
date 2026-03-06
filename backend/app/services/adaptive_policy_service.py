from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.memory_service import get_float_control, set_memory
from app.services.ops_service import collect_ops_quality_metrics


def tune_agent_controls(db: Session) -> dict:
    metrics = collect_ops_quality_metrics(db)

    current_cluster_threshold = get_float_control(
        db, "clustering_min_confidence", settings.clustering_min_confidence
    )
    new_cluster_threshold = current_cluster_threshold

    if metrics.cluster_confidence_avg < 0.5 and metrics.active_story_count > 0:
        new_cluster_threshold = min(0.78, current_cluster_threshold + 0.02)
    elif (
        metrics.cluster_confidence_avg > 0.8
        and metrics.open_exceptions_high == 0
        and metrics.bullet_compliance_rate >= 0.98
    ):
        new_cluster_threshold = max(0.50, current_cluster_threshold - 0.01)

    crawl_mode = "normal"
    if metrics.open_exceptions_high > max(1, settings.ops_max_open_high_exceptions // 2):
        crawl_mode = "conservative"
    elif (
        metrics.publish_staleness_minutes is not None
        and metrics.publish_staleness_minutes > settings.ops_max_publish_staleness_minutes
    ):
        crawl_mode = "aggressive"

    now = datetime.now(timezone.utc).isoformat()
    set_memory(
        db,
        "clustering_min_confidence",
        {
            "value": round(new_cluster_threshold, 4),
            "updated_by": "policy_tuning",
            "updated_at": now,
            "basis": {
                "cluster_confidence_avg": metrics.cluster_confidence_avg,
                "open_exceptions_high": metrics.open_exceptions_high,
            },
        },
    )
    set_memory(
        db,
        "crawl_aggressiveness",
        {
            "value": crawl_mode,
            "updated_by": "policy_tuning",
            "updated_at": now,
            "basis": {
                "publish_staleness_minutes": metrics.publish_staleness_minutes,
                "open_exceptions_high": metrics.open_exceptions_high,
            },
        },
    )
    db.commit()

    return {
        "clustering_min_confidence": round(new_cluster_threshold, 4),
        "crawl_aggressiveness": crawl_mode,
        "metrics_snapshot": {
            "cluster_confidence_avg": metrics.cluster_confidence_avg,
            "open_exceptions_high": metrics.open_exceptions_high,
            "publish_staleness_minutes": metrics.publish_staleness_minutes,
        },
    }
