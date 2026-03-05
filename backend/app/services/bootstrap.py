from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Source, SourceState, SourceType


DEFAULT_SOURCES = [
    (
        "OpenAI",
        "openai.com",
        SourceType.blog,
        0.95,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://openai.com/news/rss.xml"]},
    ),
    (
        "Anthropic",
        "anthropic.com",
        SourceType.blog,
        0.9,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://www.anthropic.com/news/rss.xml"]},
    ),
    (
        "TechCrunch",
        "techcrunch.com",
        SourceType.news,
        0.8,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://techcrunch.com/category/artificial-intelligence/feed/"]},
    ),
    (
        "The Verge",
        "theverge.com",
        SourceType.news,
        0.75,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"]},
    ),
    (
        "arXiv",
        "arxiv.org",
        SourceType.research,
        0.9,
        {
            "poll_minutes": 15,
            "timeout_seconds": 10,
            "feed_urls": ["https://rss.arxiv.org/rss/cs.AI", "https://rss.arxiv.org/rss/cs.LG"],
        },
    ),
    (
        "GitHub",
        "github.com",
        SourceType.github,
        0.85,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://github.blog/feed/"]},
    ),
]


def ensure_seed_data(db: Session) -> None:
    existing = db.execute(select(Source)).scalars().first()
    if existing:
        return

    for name, domain, source_type, authority, crawl_config in DEFAULT_SOURCES:
        db.add(
            Source(
                name=name,
                domain=domain,
                type=source_type,
                authority_score=authority,
                state=SourceState.trusted,
                crawl_config_json=crawl_config,
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
