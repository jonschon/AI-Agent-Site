from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agents.pipeline import run_pipeline, run_single_agent
from app.db.base import Base
from app.models.news import (
    Article,
    FeedSnapshot,
    RawArticle,
    Source,
    SourceState,
    SourceType,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTier,
)


def test_pipeline_e2e_smoke() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(
            Source(
                name="SmokeSource",
                domain="smoke.example.com",
                type=SourceType.news,
                authority_score=0.8,
                state=SourceState.trusted,
                crawl_config_json={"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": []},
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        results = run_pipeline(db)
        assert "crawler" in results
        assert "publishing" in results

        snapshot = db.execute(select(FeedSnapshot).order_by(FeedSnapshot.id.desc())).scalar_one_or_none()
        assert snapshot is not None

        active_stories = db.execute(select(Story).where(Story.status == StoryStatus.active)).scalars().all()
        assert len(active_stories) >= 1


def test_crawler_respects_global_and_per_source_caps(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        sources: list[Source] = []
        for idx in range(3):
            source = Source(
                name=f"S{idx + 1}",
                domain=f"s{idx + 1}.example.com",
                type=SourceType.news,
                authority_score=0.8,
                state=SourceState.trusted,
                crawl_config_json={"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": []},
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(source)
            sources.append(source)
        db.commit()

        def _fake_entries(source: Source, limit: int = 20) -> list[dict]:
            items = []
            for i in range(limit):
                items.append(
                    {
                        "url": f"https://{source.domain}/story-{i}",
                        "title": f"{source.name} story {i}",
                        "content": "content",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "fingerprint": f"{source.id}-{i}",
                        "feed_url": f"https://{source.domain}/feed.xml",
                    }
                )
            return items

        from app.core.config import settings

        monkeypatch.setattr("app.agents.pipeline.fetch_feed_entries", _fake_entries)
        monkeypatch.setattr(settings, "crawler_fetch_limit_per_source", 10)
        monkeypatch.setattr(settings, "crawler_max_new_articles_per_source", 2)
        monkeypatch.setattr(settings, "crawler_max_new_articles_per_cycle", 5)

        run_single_agent(db, "crawler")

        raws = db.execute(select(RawArticle)).scalars().all()
        assert len(raws) == 5
        counts: dict[int, int] = {}
        for raw in raws:
            counts[raw.source_id] = counts.get(raw.source_id, 0) + 1
        assert all(value <= 2 for value in counts.values())
        assert len(counts) >= 2


def test_summarization_skips_unchanged_story(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        source = Source(
            name="S",
            domain="s.example.com",
            type=SourceType.news,
            authority_score=0.8,
            state=SourceState.trusted,
            crawl_config_json={},
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(source)
        db.flush()

        article = Article(
            source_id=source.id,
            canonical_url="https://s.example.com/a1",
            title="A title",
            content_text="A body",
            snippet="A body",
            published_at=datetime.now(timezone.utc),
            content_hash="a" * 64,
            language="en",
        )
        db.add(article)
        db.flush()

        story = Story(
            slug="story-a",
            headline="Seed headline",
            bullets_json=["seed bullet"],
            tier=StoryTier.quick,
            status=StoryStatus.active,
            importance_score=0.65,
            first_seen_at=datetime.now(timezone.utc),
            last_updated_at=datetime.now(timezone.utc),
        )
        db.add(story)
        db.flush()
        db.add(StoryArticle(story_id=story.id, article_id=article.id, cluster_confidence=0.9))
        db.commit()

        from app.core.config import settings

        calls = {"count": 0}

        def _fake_summarize(headline_seed: str, snippets: list[str], max_bullets: int = 3):
            del headline_seed, snippets
            calls["count"] += 1
            return "Updated headline", [f"bullet {i+1}" for i in range(max_bullets)]

        monkeypatch.setattr(settings, "summarization_skip_unchanged", True)
        monkeypatch.setattr("app.agents.pipeline.summarize_story", _fake_summarize)

        run_single_agent(db, "summarization_tagging")
        assert calls["count"] == 1

        run_single_agent(db, "summarization_tagging")
        assert calls["count"] == 1
