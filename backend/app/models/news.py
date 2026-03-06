from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SourceState(str, enum.Enum):
    trusted = "trusted"
    watchlist = "watchlist"
    blocked = "blocked"


class SourceType(str, enum.Enum):
    blog = "blog"
    news = "news"
    github = "github"
    research = "research"
    discussion = "discussion"


class StoryTier(str, enum.Enum):
    lead = "lead"
    major = "major"
    quick = "quick"
    archived = "archived"


class StoryStatus(str, enum.Enum):
    active = "active"
    stale = "stale"
    archived = "archived"


class RunStatus(str, enum.Enum):
    success = "success"
    failed = "failed"
    running = "running"


class ExceptionStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    authority_score: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    state: Mapped[SourceState] = mapped_column(Enum(SourceState), default=SourceState.trusted)
    crawl_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RawArticle(Base):
    __tablename__ = "raw_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), default="en")


class ArticleEmbedding(Base):
    __tablename__ = "article_embeddings"

    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    # Use JSON list for portability; pgvector can replace this in production migrations.
    embedding: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    bullets_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    tier: Mapped[StoryTier] = mapped_column(Enum(StoryTier), default=StoryTier.quick)
    status: Mapped[StoryStatus] = mapped_column(Enum(StoryStatus), default=StoryStatus.active)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    articles: Mapped[list[StoryArticle]] = relationship(back_populates="story", cascade="all, delete-orphan")
    tags: Mapped[list[StoryTag]] = relationship(back_populates="story", cascade="all, delete-orphan")
    discussions: Mapped[list[DiscussionLink]] = relationship(back_populates="story", cascade="all, delete-orphan")


class StoryArticle(Base):
    __tablename__ = "story_articles"

    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id"), primary_key=True)
    cluster_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_primary: Mapped[bool] = mapped_column(default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="articles")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)


class StoryTag(Base):
    __tablename__ = "story_tags"

    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    story: Mapped[Story] = relationship(back_populates="tags")


class DiscussionLink(Base):
    __tablename__ = "discussion_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    engagement_score: Mapped[float] = mapped_column(Float, default=0.0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="discussions")


class FeedSnapshot(Base):
    __tablename__ = "feed_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    lead_story_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stories.id"), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class FeedSnapshotItem(Base):
    __tablename__ = "feed_snapshot_items"
    __table_args__ = (UniqueConstraint("snapshot_id", "story_id", name="uq_snapshot_story"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("feed_snapshots.id"), nullable=False)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), nullable=False)
    section: Mapped[str] = mapped_column(String(100), nullable=False, default="All")
    tier: Mapped[StoryTier] = mapped_column(Enum(StoryTier), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    rank: Mapped[int] = mapped_column(Integer, default=0)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.running)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExceptionItem(Base):
    __tablename__ = "exceptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[ExceptionStatus] = mapped_column(Enum(ExceptionStatus), default=ExceptionStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMemory(Base):
    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
