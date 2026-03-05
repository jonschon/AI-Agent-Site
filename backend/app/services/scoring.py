from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.news import Story

LEAD_MAX_HOURS = 24
MAJOR_MAX_HOURS = 24
QUICK_MAX_HOURS = 48


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_source_diversity(source_diversity: int) -> float:
    return _clamp(source_diversity / 10.0)


def normalize_recency(hours_old: float) -> float:
    return _clamp(1.0 - min(hours_old / 48.0, 1.0))


def normalize_discussion_velocity(discussion_velocity: float) -> float:
    return _clamp(discussion_velocity / 100.0)


def score_story(
    source_diversity: int,
    authority: float,
    hours_old: float,
    discussion_velocity: float,
    entity_weight: float,
    w_authority: float = 0.30,
    w_diversity: float = 0.27,
    w_recency: float = 0.23,
    w_discussion: float = 0.12,
    w_entity: float = 0.08,
) -> float:
    recency = normalize_recency(hours_old)
    return (
        (w_authority * _clamp(authority))
        + (w_diversity * normalize_source_diversity(source_diversity))
        + (w_recency * recency)
        + (w_discussion * normalize_discussion_velocity(discussion_velocity))
        + (w_entity * _clamp(entity_weight))
    )


def momentum(previous_score: float, current_score: float, new_sources: int) -> float:
    return (current_score - previous_score) + min(new_sources / 10.0, 0.5)


def apply_retention_tier(story: Story, now: Optional[datetime] = None) -> str:
    now = _ensure_aware(now or datetime.now(timezone.utc))
    age = now - _ensure_aware(story.first_seen_at)
    hours = age.total_seconds() / 3600

    if story.tier.value == "lead" and hours > LEAD_MAX_HOURS:
        return "major"
    if story.tier.value == "major" and hours > MAJOR_MAX_HOURS:
        return "quick"
    if story.tier.value == "quick" and hours > QUICK_MAX_HOURS:
        return "archived"
    return story.tier.value


def badges_for_story(is_new: bool, momentum_score: float, new_sources: int, updated_recently: bool) -> list[str]:
    badges: list[str] = []
    if is_new:
        badges.append("NEW")
    if momentum_score > 0.25:
        badges.append("Trending")
    if new_sources > 0:
        badges.append(f"+{new_sources} sources")
    if updated_recently:
        badges.append("Updated")
    return badges


def is_new_story(first_seen_at: datetime, now: Optional[datetime] = None) -> bool:
    now = _ensure_aware(now or datetime.now(timezone.utc))
    return _ensure_aware(first_seen_at) >= (now - timedelta(minutes=30))
