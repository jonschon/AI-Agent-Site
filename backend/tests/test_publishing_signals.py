from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.pipeline import PublishingAgent
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
