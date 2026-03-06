from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.news import (
    AgentRun,
    Article,
    DiscussionLink,
    ExceptionItem,
    FeedSnapshot,
    FeedSnapshotItem,
    Signal,
    Source,
    Story,
    StoryArticle,
    StoryStatus,
    StoryTag,
    Tag,
)
from app.schemas.news import (
    AgentRunOut,
    DiscussionLinkOut,
    ExceptionOut,
    FeedResponse,
    NewsroomStats,
    SectionBlock,
    SectionsResponse,
    SignalWidget,
    SourceLink,
    StoryCard,
    StoryDetail,
)
from app.services.scoring import badges_for_story, is_new_story


def _to_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _story_card(db: Session, story: Story) -> StoryCard:
    source_rows = db.execute(
        select(Source.name, Article.canonical_url)
        .join(Article, Article.source_id == Source.id)
        .join(StoryArticle, StoryArticle.article_id == Article.id)
        .where(StoryArticle.story_id == story.id)
        .order_by(desc(Article.published_at))
        .limit(6)
    ).all()
    sources = [SourceLink(source_name=name, url=url) for name, url in source_rows]

    tags_rows = db.execute(
        select(Tag.name)
        .join(StoryTag, StoryTag.tag_id == Tag.id)
        .where(StoryTag.story_id == story.id)
    ).scalars().all()

    discussions = db.execute(
        select(DiscussionLink)
        .where(DiscussionLink.story_id == story.id)
        .order_by(desc(DiscussionLink.engagement_score))
        .limit(3)
    ).scalars().all()

    now = datetime.now(timezone.utc)
    new_sources = max(len(sources) - 1, 0)
    updated_recently = (now - _to_aware_utc(story.last_updated_at)).total_seconds() < 3600
    badges = badges_for_story(
        is_new=is_new_story(story.first_seen_at, now),
        momentum_score=story.momentum_score,
        new_sources=new_sources,
        updated_recently=updated_recently,
    )

    return StoryCard(
        id=story.id,
        slug=story.slug,
        headline=story.headline,
        bullets=(story.bullets_json or ["", "", ""])[:3],
        tags=tags_rows,
        sources=sources,
        discussions=[DiscussionLinkOut(platform=d.platform, url=d.url) for d in discussions],
        importance_score=story.importance_score,
        momentum_score=story.momentum_score,
        tier=story.tier.value,
        badges=badges,
        updated_at=_to_aware_utc(story.last_updated_at),
    )


def get_feed(db: Session) -> FeedResponse:
    snapshot = db.execute(select(FeedSnapshot).order_by(desc(FeedSnapshot.published_at)).limit(1)).scalar_one_or_none()
    if not snapshot:
        return FeedResponse(published_at=datetime.now(timezone.utc), lead_story=None, major_stories=[], quick_updates=[])

    items = db.execute(
        select(FeedSnapshotItem, Story)
        .join(Story, Story.id == FeedSnapshotItem.story_id)
        .where(FeedSnapshotItem.snapshot_id == snapshot.id)
        .order_by(FeedSnapshotItem.position)
    ).all()

    lead = None
    major: list[StoryCard] = []
    quick: list[StoryCard] = []

    for item, story in items:
        card = _story_card(db, story)
        if item.tier.value == "lead":
            lead = card
        elif item.tier.value == "major":
            major.append(card)
        elif item.tier.value == "quick":
            quick.append(card)

    return FeedResponse(
        published_at=snapshot.published_at,
        lead_story=lead,
        major_stories=major,
        quick_updates=quick,
    )


def get_sections(db: Session) -> SectionsResponse:
    stories = db.execute(
        select(Story).where(Story.status == StoryStatus.active).order_by(desc(Story.importance_score)).limit(40)
    ).scalars().all()

    bucket: dict[str, list[StoryCard]] = defaultdict(list)
    for story in stories:
        tags = db.execute(
            select(Tag.name)
            .join(StoryTag, StoryTag.tag_id == Tag.id)
            .where(StoryTag.story_id == story.id)
        ).scalars().all()
        section = tags[0] if tags else "Research"
        bucket[section].append(_story_card(db, story))

    ordered = [SectionBlock(name=name, stories=cards[:8]) for name, cards in bucket.items()]
    return SectionsResponse(sections=ordered)


def get_story_detail(db: Session, slug: str) -> Optional[StoryDetail]:
    story = db.execute(select(Story).where(Story.slug == slug)).scalar_one_or_none()
    if not story:
        return None
    card = _story_card(db, story)
    return StoryDetail(**card.model_dump(), related_sources_count=len(card.sources))


def list_stories(
    db: Session, category: Optional[str], tag: Optional[str], tier: Optional[str], limit: int = 30
) -> list[StoryCard]:
    stmt = select(Story).order_by(desc(Story.importance_score), desc(Story.last_updated_at)).limit(limit)
    if tier:
        stmt = stmt.where(Story.tier == tier)

    stories = db.execute(stmt).scalars().all()
    out: list[StoryCard] = []
    for story in stories:
        card = _story_card(db, story)
        if category and category not in card.tags:
            continue
        if tag and tag not in card.tags:
            continue
        out.append(card)
    return out


def get_signals(db: Session) -> list[SignalWidget]:
    rows = db.execute(select(Signal).order_by(desc(Signal.observed_at), Signal.rank).limit(20)).scalars().all()
    return [
        SignalWidget(type=s.signal_type, title=s.title, data=s.value_json, observed_at=s.observed_at)
        for s in rows
    ]


def search_stories(db: Session, q: str) -> list[StoryCard]:
    stories = db.execute(
        select(Story)
        .where(Story.headline.ilike(f"%{q}%"))
        .order_by(desc(Story.importance_score))
        .limit(20)
    ).scalars().all()
    return [_story_card(db, story) for story in stories]


def newsroom_stats(db: Session) -> NewsroomStats:
    article_count = db.execute(select(func.count(Article.id))).scalar_one()
    story_count = db.execute(select(func.count(Story.id))).scalar_one()
    last_update = db.execute(select(func.max(FeedSnapshot.published_at))).scalar_one_or_none()
    return NewsroomStats(
        articles_processed=article_count,
        stories_detected=story_count,
        last_update_time=last_update,
    )


def get_agent_runs(db: Session) -> list[AgentRunOut]:
    rows = db.execute(select(AgentRun).order_by(desc(AgentRun.started_at)).limit(50)).scalars().all()
    return [
        AgentRunOut(
            id=r.id,
            agent_name=r.agent_name,
            started_at=r.started_at,
            ended_at=r.ended_at,
            status=r.status.value,
            metrics=r.metrics_json,
            error_text=r.error_text,
        )
        for r in rows
    ]


def get_exceptions(db: Session) -> list[ExceptionOut]:
    rows = db.execute(
        select(ExceptionItem).where(ExceptionItem.status == "open").order_by(desc(ExceptionItem.created_at))
    ).scalars().all()
    return [
        ExceptionOut(
            id=e.id,
            agent_name=e.agent_name,
            object_type=e.object_type,
            object_id=e.object_id,
            reason=e.reason,
            severity=e.severity,
            status=e.status.value,
            created_at=e.created_at,
            resolved_at=e.resolved_at,
        )
        for e in rows
    ]
