from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.main import app
from app.services.bootstrap import ensure_seed_data

client = TestClient(app)


EXPECTED_FEED_KEYS = {"published_at", "lead_story", "major_stories", "quick_updates"}
EXPECTED_STORY_KEYS = {
    "id",
    "slug",
    "headline",
    "bullets",
    "tags",
    "sources",
    "discussions",
    "importance_score",
    "momentum_score",
    "tier",
    "badges",
    "updated_at",
}
EXPECTED_SOURCE_KEYS = {"source_name", "url"}
EXPECTED_DISCUSSION_KEYS = {"platform", "url"}
EXPECTED_SIGNAL_KEYS = {"type", "title", "data", "observed_at"}
EXPECTED_NEWSROOM_KEYS = {"articles_processed", "stories_detected", "last_update_time"}


def _assert_story_shape(story: dict) -> None:
    assert set(story.keys()) == EXPECTED_STORY_KEYS
    assert isinstance(story["id"], int)
    assert isinstance(story["slug"], str)
    assert isinstance(story["headline"], str)
    assert isinstance(story["bullets"], list)
    assert len(story["bullets"]) == 3
    assert all(isinstance(item, str) for item in story["bullets"])
    assert isinstance(story["tags"], list)
    assert isinstance(story["sources"], list)
    assert isinstance(story["discussions"], list)
    assert isinstance(story["importance_score"], (float, int))
    assert isinstance(story["momentum_score"], (float, int))
    assert isinstance(story["tier"], str)
    assert isinstance(story["badges"], list)
    datetime.fromisoformat(story["updated_at"].replace("Z", "+00:00"))

    for source in story["sources"]:
        assert set(source.keys()) == EXPECTED_SOURCE_KEYS
        assert isinstance(source["source_name"], str)
        assert isinstance(source["url"], str)

    for discussion in story["discussions"]:
        assert set(discussion.keys()) == EXPECTED_DISCUSSION_KEYS
        assert isinstance(discussion["platform"], str)
        assert isinstance(discussion["url"], str)


def _prime_pipeline(monkeypatch) -> None:
    from app.core.config import settings

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_seed_data(db)
    finally:
        db.close()

    # Keep contract tests offline-friendly.
    monkeypatch.setattr("app.agents.pipeline.fetch_feed_entries", lambda source, limit=15: [])

    response = client.post(
        "/v1/internal/agents/run/all",
        headers={"x-internal-api-key": settings.internal_api_key},
    )
    assert response.status_code == 200


def test_feed_contract(monkeypatch) -> None:
    _prime_pipeline(monkeypatch)

    response = client.get("/v1/feed")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == EXPECTED_FEED_KEYS
    datetime.fromisoformat(payload["published_at"].replace("Z", "+00:00"))
    assert isinstance(payload["major_stories"], list)
    assert isinstance(payload["quick_updates"], list)

    if payload["lead_story"] is not None:
        _assert_story_shape(payload["lead_story"])

    for story in payload["major_stories"]:
        _assert_story_shape(story)

    for story in payload["quick_updates"]:
        _assert_story_shape(story)


def test_signals_contract(monkeypatch) -> None:
    _prime_pipeline(monkeypatch)

    response = client.get("/v1/signals")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)

    for signal in payload:
        assert set(signal.keys()) == EXPECTED_SIGNAL_KEYS
        assert isinstance(signal["type"], str)
        assert isinstance(signal["title"], str)
        assert isinstance(signal["data"], dict)
        datetime.fromisoformat(signal["observed_at"].replace("Z", "+00:00"))


def test_newsroom_stats_contract(monkeypatch) -> None:
    _prime_pipeline(monkeypatch)

    response = client.get("/v1/stats/newsroom")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == EXPECTED_NEWSROOM_KEYS
    assert isinstance(payload["articles_processed"], int)
    assert isinstance(payload["stories_detected"], int)
    if payload["last_update_time"] is not None:
        datetime.fromisoformat(payload["last_update_time"].replace("Z", "+00:00"))
