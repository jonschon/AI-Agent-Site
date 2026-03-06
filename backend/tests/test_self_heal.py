from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import CrawlerAgent, SelfHealAgent
from app.core.config import settings
from app.db.base import Base
from app.models.news import ExceptionItem, ExceptionStatus, Source, SourceState, SourceType


def test_self_heal_auto_resolves_stale_low_severity(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        stale = ExceptionItem(
            agent_name="monitoring_qa",
            object_type="story",
            object_id="1",
            reason="minor issue",
            severity="medium",
            status=ExceptionStatus.open,
            created_at=datetime.now(timezone.utc) - timedelta(hours=10),
        )
        fresh = ExceptionItem(
            agent_name="monitoring_qa",
            object_type="story",
            object_id="2",
            reason="fresh issue",
            severity="medium",
            status=ExceptionStatus.open,
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([stale, fresh])
        db.commit()

        monkeypatch.setattr(settings, "self_heal_exception_stale_minutes", 60)
        result = SelfHealAgent().run(db)
        assert result.updated == 1

        refreshed = db.execute(select(ExceptionItem).order_by(ExceptionItem.id)).scalars().all()
        assert refreshed[0].status == ExceptionStatus.resolved
        assert refreshed[1].status == ExceptionStatus.open


def test_crawler_source_failure_triggers_cooldown(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source = Source(
            name="FailingFeed",
            domain="failing.example.com",
            type=SourceType.news,
            authority_score=0.4,
            state=SourceState.trusted,
            crawl_config_json={"feed_urls": ["https://failing.example.com/feed.xml"], "poll_minutes": 10},
            is_active=True,
        )
        db.add(source)
        db.commit()

        monkeypatch.setattr("app.agents.pipeline.fetch_feed_entries", lambda source, limit=15: (_ for _ in ()).throw(RuntimeError("feed error")))
        monkeypatch.setattr(settings, "self_heal_max_source_failures", 1)
        monkeypatch.setattr(settings, "self_heal_source_cooldown_minutes", 20)

        result = CrawlerAgent().run(db)
        assert result.processed == 1

        updated_source = db.execute(select(Source).where(Source.id == source.id)).scalar_one()
        assert updated_source.state == SourceState.watchlist
        cfg = updated_source.crawl_config_json
        assert cfg.get("crawl_failures", 0) >= 1
        assert isinstance(cfg.get("cooldown_until"), str)

        created_exceptions = db.execute(select(ExceptionItem)).scalars().all()
        assert len(created_exceptions) >= 1
