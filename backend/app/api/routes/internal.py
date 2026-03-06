from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline, run_pipeline_steps, run_single_agent
from app.core.config import settings
from app.db.session import get_db
from app.models.news import ExceptionItem, ExceptionStatus
from app.schemas.internal import ResolveExceptionRequest
from app.schemas.news import (
    AgentRunOut,
    AutonomousCycleResult,
    ExceptionOut,
    OpsPolicyEvaluation,
    OpsQualityMetrics,
)
from app.services.feed_service import get_agent_runs, get_exceptions
from app.services.memory_service import list_memory
from app.services.ops_service import collect_ops_quality_metrics, evaluate_ops_policy, evaluate_prepublish_policy

router = APIRouter(prefix="/internal")


def _check_internal_auth(x_internal_api_key: Optional[str] = Header(default=None)) -> None:
    if x_internal_api_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/agents/run/{agent_name}")
def trigger_agent_run(
    agent_name: str,
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> dict:
    if agent_name == "all":
        return {"results": run_pipeline(db)}
    return run_single_agent(db, agent_name)


@router.get("/agent-runs", response_model=list[AgentRunOut])
def read_agent_runs(db: Session = Depends(get_db), _: None = Depends(_check_internal_auth)) -> list[AgentRunOut]:
    return get_agent_runs(db)


@router.get("/exceptions", response_model=list[ExceptionOut])
def read_exceptions(db: Session = Depends(get_db), _: None = Depends(_check_internal_auth)) -> list[ExceptionOut]:
    return get_exceptions(db)


@router.post("/exceptions/{exception_id}/resolve")
def resolve_exception(
    exception_id: int,
    payload: ResolveExceptionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> dict:
    exc = db.execute(select(ExceptionItem).where(ExceptionItem.id == exception_id)).scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
    exc.status = ExceptionStatus.resolved
    exc.resolved_at = datetime.now(timezone.utc)
    merged = exc.payload_json or {}
    if payload.note:
        merged["resolution_note"] = payload.note
    exc.payload_json = merged
    db.add(exc)
    db.commit()
    return {"status": "resolved", "id": exception_id}


@router.get("/ops/quality", response_model=OpsQualityMetrics)
def read_ops_quality(
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> OpsQualityMetrics:
    return collect_ops_quality_metrics(db)


@router.get("/ops/policy-eval", response_model=OpsPolicyEvaluation)
def read_ops_policy_eval(
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> OpsPolicyEvaluation:
    return evaluate_ops_policy(db)


@router.post("/ops/autonomous-cycle", response_model=AutonomousCycleResult)
def run_autonomous_cycle(
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> AutonomousCycleResult:
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
        "policy_tuning",
    ]
    results = run_pipeline_steps(db, prepublish_steps)
    prepublish_policy = evaluate_prepublish_policy(db)
    if prepublish_policy.status == "pass":
        publish_result = run_single_agent(db, "publishing")
        results["publishing"] = {
            "processed": publish_result["processed"],
            "created": publish_result["created"],
            "updated": publish_result["updated"],
        }
        return AutonomousCycleResult(
            status="pass",
            action="published",
            blocking_reasons=[],
            prepublish_metrics=prepublish_policy.metrics,
            pipeline_results=results,
        )

    db.add(
        ExceptionItem(
            agent_name="autonomous_cycle",
            object_type="cycle",
            object_id=datetime.now(timezone.utc).isoformat(),
            reason="Autonomous cycle held due to policy blockers",
            severity="high",
            payload_json={
                "blocking_reasons": prepublish_policy.blocking_reasons,
                "generated_at": prepublish_policy.metrics.generated_at.isoformat(),
            },
        )
    )
    db.commit()

    return AutonomousCycleResult(
        status="hold",
        action="hold",
        blocking_reasons=prepublish_policy.blocking_reasons,
        prepublish_metrics=prepublish_policy.metrics,
        pipeline_results=results,
    )


@router.get("/ops/controls")
def read_ops_controls(
    db: Session = Depends(get_db),
    _: None = Depends(_check_internal_auth),
) -> dict:
    rows = list_memory(db)
    controls = []
    for row in rows:
        controls.append({"key": row.key, "value": row.value_json, "updated_at": row.updated_at.isoformat()})
    return {"controls": controls}
