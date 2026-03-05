from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.news import Source, SourceState, SourceType


DEFAULT_SOURCES = [
    ("OpenAI", "openai.com", SourceType.blog, 0.95),
    ("Anthropic", "anthropic.com", SourceType.blog, 0.9),
    ("TechCrunch", "techcrunch.com", SourceType.news, 0.8),
    ("The Verge", "theverge.com", SourceType.news, 0.75),
    ("arXiv", "arxiv.org", SourceType.research, 0.9),
    ("GitHub", "github.com", SourceType.github, 0.85),
]


def ensure_seed_data(db: Session) -> None:
    existing = db.execute(select(Source)).scalars().first()
    if existing:
        return

    for name, domain, source_type, authority in DEFAULT_SOURCES:
        db.add(
            Source(
                name=name,
                domain=domain,
                type=source_type,
                authority_score=authority,
                state=SourceState.trusted,
                crawl_config_json={"poll_minutes": 10, "timeout_seconds": 10},
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    db.commit()
