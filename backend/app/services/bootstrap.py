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
    (
        "Google DeepMind",
        "deepmind.google",
        SourceType.blog,
        0.9,
        {"poll_minutes": 15, "timeout_seconds": 10, "feed_urls": ["https://deepmind.google/discover/blog/rss.xml"]},
    ),
    (
        "Google AI Blog",
        "blog.google",
        SourceType.blog,
        0.88,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://blog.google/technology/ai/rss/"]},
    ),
    (
        "Meta AI",
        "ai.meta.com",
        SourceType.blog,
        0.86,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://ai.meta.com/blog/rss/"]},
    ),
    (
        "NVIDIA Blog",
        "blogs.nvidia.com",
        SourceType.blog,
        0.84,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://blogs.nvidia.com/feed/"]},
    ),
    (
        "Microsoft Azure Blog",
        "azure.microsoft.com",
        SourceType.blog,
        0.82,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://azure.microsoft.com/en-us/blog/feed/"]},
    ),
    (
        "AWS News Blog",
        "aws.amazon.com",
        SourceType.blog,
        0.82,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://aws.amazon.com/blogs/aws/feed/"]},
    ),
    (
        "Google Cloud Blog",
        "cloud.google.com",
        SourceType.blog,
        0.82,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://cloud.google.com/blog/topics/ai-ml/rss/"]},
    ),
    (
        "OpenAI Cookbook",
        "cookbook.openai.com",
        SourceType.blog,
        0.78,
        {"poll_minutes": 30, "timeout_seconds": 10, "feed_urls": ["https://cookbook.openai.com/rss.xml"]},
    ),
    (
        "Hugging Face Blog",
        "huggingface.co",
        SourceType.blog,
        0.8,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://huggingface.co/blog/feed.xml"]},
    ),
    (
        "Mistral AI News",
        "mistral.ai",
        SourceType.blog,
        0.8,
        {"poll_minutes": 25, "timeout_seconds": 10, "feed_urls": ["https://mistral.ai/news/rss.xml"]},
    ),
    (
        "The Batch (DeepLearning.AI)",
        "deeplearning.ai",
        SourceType.news,
        0.76,
        {"poll_minutes": 30, "timeout_seconds": 10, "feed_urls": ["https://www.deeplearning.ai/the-batch/feed/"]},
    ),
    (
        "VentureBeat AI",
        "venturebeat.com",
        SourceType.news,
        0.78,
        {"poll_minutes": 15, "timeout_seconds": 10, "feed_urls": ["https://venturebeat.com/ai/feed/"]},
    ),
    (
        "Wired AI",
        "wired.com",
        SourceType.news,
        0.75,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://www.wired.com/feed/tag/ai/latest/rss"]},
    ),
    (
        "MIT Technology Review AI",
        "technologyreview.com",
        SourceType.news,
        0.8,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://www.technologyreview.com/topic/artificial-intelligence/feed/"]},
    ),
    (
        "Semafor Technology",
        "semafor.com",
        SourceType.news,
        0.72,
        {"poll_minutes": 25, "timeout_seconds": 10, "feed_urls": ["https://www.semafor.com/feed"]},
    ),
    (
        "Ars Technica AI",
        "arstechnica.com",
        SourceType.news,
        0.76,
        {"poll_minutes": 20, "timeout_seconds": 10, "feed_urls": ["https://feeds.arstechnica.com/arstechnica/technology-lab"]},
    ),
    (
        "Tom's Hardware AI",
        "tomshardware.com",
        SourceType.news,
        0.68,
        {"poll_minutes": 30, "timeout_seconds": 10, "feed_urls": ["https://www.tomshardware.com/feeds/all"]},
    ),
    (
        "Papers with Code",
        "paperswithcode.com",
        SourceType.research,
        0.74,
        {"poll_minutes": 25, "timeout_seconds": 10, "feed_urls": ["https://paperswithcode.com/rss/latest"]},
    ),
    (
        "Hacker News",
        "news.ycombinator.com",
        SourceType.discussion,
        0.7,
        {"poll_minutes": 10, "timeout_seconds": 10, "feed_urls": ["https://news.ycombinator.com/rss"]},
    ),
    (
        "Reddit Machine Learning",
        "reddit.com",
        SourceType.discussion,
        0.64,
        {"poll_minutes": 15, "timeout_seconds": 10, "feed_urls": ["https://www.reddit.com/r/MachineLearning/.rss"]},
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
