from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.pipeline import LeaderboardValidationAgent, PublishingAgent
from app.db.base import Base
from app.models.news import Signal


def test_publishing_rankings_have_minimum_candidates_without_story_inputs() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    agent = PublishingAgent()

    with Session(engine) as db:
        mau = agent._build_app_mau(db, [])
        models = agent._build_foundation_model_gpqa(db, [])
        builders = agent._build_model_builder_valuation(db, [])
        infra = agent._build_infrastructure_compute_capacity(db, [])

        assert len(mau) >= 4
        assert len(models) >= 4
        assert len(builders) >= 3
        assert len(infra) >= 3


def test_funding_tracker_ignores_non_entity_keys_from_previous_signal() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    agent = PublishingAgent()

    with Session(engine) as db:
        db.add(
            Signal(
                signal_type="funding_tracker",
                title="Model Builders",
                value_json={"items": 2, "OpenAI": 250.0},
                observed_at=datetime.now(timezone.utc),
                rank=1,
            )
        )
        db.commit()

        builders = agent._build_model_builder_valuation(db, [])
        assert "items" not in builders
        assert "OpenAI" in builders
        assert builders["OpenAI"] >= 300.0


def test_signal_payload_includes_rows_with_confidence_and_source_count() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    agent = PublishingAgent()

    with Session(engine) as db:
        payload = agent._build_signal_payload_with_rows(
            db,
            [],
            {
                "OpenAI": 300.0,
                "Anthropic": 60.0,
            },
        )
        rows = payload.get("rows")
        assert isinstance(rows, list)
        assert len(rows) == 2
        first = rows[0]
        assert isinstance(first, dict)
        assert "confidence" in first
        assert "source_count" in first
        assert "evidence_urls" in first


def test_leaderboard_validation_agent_drops_rows_without_evidence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    validator = LeaderboardValidationAgent()

    with Session(engine) as db:
        db.add(
            Signal(
                signal_type="app_adoption",
                title="Monthly Active Users",
                value_json={
                    "ChatGPT": 300.0,
                    "Claude": 25.0,
                    "rows": [
                        {
                            "entity": "ChatGPT",
                            "value": 300.0,
                            "confidence": "high",
                            "source_count": 2,
                            "evidence_urls": ["https://example.com/a"],
                        },
                        {
                            "entity": "Claude",
                            "value": 25.0,
                            "confidence": "estimated",
                            "source_count": 0,
                            "evidence_urls": [],
                        },
                    ],
                },
                observed_at=datetime.now(timezone.utc),
                rank=1,
            )
        )
        db.commit()

        result = validator.run(db)
        assert result.processed == 1

        latest = db.query(Signal).filter(Signal.signal_type == "app_adoption").order_by(Signal.id.desc()).first()
        assert latest is not None
        rows = latest.value_json.get("rows")
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["entity"] == "ChatGPT"
        assert "Claude" not in latest.value_json


def test_valuation_extraction_requires_context() -> None:
    agent = PublishingAgent()
    with_context = "OpenAI valuation reached $300 billion after a funding round."
    without_context = "Company reported $300 billion in annual revenue."

    vals_with = agent._extract_valuations_billions_with_context(with_context.lower())
    vals_without = agent._extract_valuations_billions_with_context(without_context.lower())

    assert vals_with == [300.0]
    assert vals_without == []


def test_outlier_guard_blocks_unconfirmed_large_jumps() -> None:
    agent = PublishingAgent()
    current = {"OpenAI": 1000.0, "Anthropic": 120.0}
    previous = {"OpenAI": 300.0, "Anthropic": 60.0}
    support = {"OpenAI": 1, "Anthropic": 2}

    guarded = agent._apply_outlier_guard(current, previous, support, max_ratio=3.0)

    assert guarded["OpenAI"] == 300.0
    assert guarded["Anthropic"] == 120.0
