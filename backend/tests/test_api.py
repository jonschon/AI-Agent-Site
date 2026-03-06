from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.news import OpsQualityMetrics, OpsPolicyEvaluation


client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/v1/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_internal_autonomous_cycle_publish(monkeypatch) -> None:
    import app.api.routes.internal as internal_routes
    from app.core.config import settings

    monkeypatch.setattr(
        internal_routes,
        "run_pipeline_steps",
        lambda db, steps: {"crawler": {"processed": 1, "created": 1, "updated": 0}},
    )
    monkeypatch.setattr(
        internal_routes,
        "evaluate_prepublish_policy",
        lambda db: OpsPolicyEvaluation(
            status="pass",
            blocking_reasons=[],
            metrics=OpsQualityMetrics(
                generated_at=datetime.now(timezone.utc),
                publish_staleness_minutes=5.0,
                open_exceptions_total=0,
                open_exceptions_high=0,
                bullet_compliance_rate=1.0,
                cluster_confidence_avg=0.8,
                cluster_confidence_low_count=0,
                merged_story_count_24h=0,
                failed_agent_runs_24h=0,
                active_story_count=5,
                agent_last_run={},
            ),
        ),
    )
    monkeypatch.setattr(
        internal_routes,
        "run_single_agent",
        lambda db, name: {"agent": name, "processed": 5, "created": 1, "updated": 0},
    )
    response = client.post(
        "/v1/internal/ops/autonomous-cycle",
        headers={"x-internal-api-key": settings.internal_api_key},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pass"
    assert payload["action"] == "published"
