from __future__ import annotations

import logging
import time

from app.agents.pipeline import run_pipeline
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.ops_service import evaluate_prepublish_policy

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def run_once() -> dict:
    db = SessionLocal()
    try:
        return run_pipeline(db)
    finally:
        db.close()


def run_once_autonomous() -> dict:
    from app.agents.pipeline import run_pipeline_steps, run_single_agent
    from app.models.news import ExceptionItem
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        prepublish_steps = [
            "crawler",
            "normalization",
            "embedding",
            "clustering",
            "merge_clusters",
            "summarization_tagging",
            "ranking",
            "monitoring_qa",
            "self_heal",
        ]
        results = run_pipeline_steps(db, prepublish_steps)
        policy = evaluate_prepublish_policy(db)
        if policy.status == "pass":
            results["publishing"] = run_single_agent(db, "publishing")
            logger.info("Autonomous cycle published successfully")
            return {"status": "pass", "action": "published", "results": results}

        db.add(
            ExceptionItem(
                agent_name="autonomous_cycle",
                object_type="cycle",
                object_id=datetime.now(timezone.utc).isoformat(),
                reason="Autonomous scheduler hold",
                severity="high",
                payload_json={
                    "blocking_reasons": policy.blocking_reasons,
                    "generated_at": policy.metrics.generated_at.isoformat(),
                },
            )
        )
        db.commit()
        logger.warning("Autonomous cycle held: %s", policy.blocking_reasons)
        return {"status": "hold", "action": "hold", "results": results, "blocking_reasons": policy.blocking_reasons}
    finally:
        db.close()


def run_forever() -> None:
    interval = settings.publish_interval_minutes * 60
    while True:
        run_once_autonomous()
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
