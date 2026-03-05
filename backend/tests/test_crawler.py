from datetime import datetime, timezone

from app.models.news import Source, SourceType
from app.services.crawler import canonicalize_url, fetch_feed_entries


class _Parsed:
    def __init__(self, entries):
        self.entries = entries


def test_canonicalize_url_removes_tracking_params() -> None:
    url = "https://example.com/path?a=1&utm_source=x&fbclid=y"
    assert canonicalize_url(url) == "https://example.com/path?a=1"


def test_fetch_feed_entries_parses_entries(monkeypatch) -> None:
    source = Source(
        name="Test",
        domain="example.com",
        type=SourceType.news,
        authority_score=0.8,
        crawl_config_json={"feed_urls": ["https://example.com/feed.xml"]},
        is_active=True,
    )

    def _fake_parse(_: str):
        return _Parsed(
            [
                {
                    "link": "https://example.com/story?utm_medium=social",
                    "title": "AI Story",
                    "summary": "A summary",
                    "published_parsed": datetime(2026, 1, 1, tzinfo=timezone.utc).timetuple(),
                }
            ]
        )

    monkeypatch.setattr("app.services.crawler.feedparser.parse", _fake_parse)

    entries = fetch_feed_entries(source)
    assert len(entries) == 1
    assert entries[0]["url"] == "https://example.com/story"
    assert entries[0]["title"] == "AI Story"
    assert entries[0]["content"]
