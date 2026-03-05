from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.news import Story

LEAD_MAX_HOURS = 24
MAJOR_MAX_HOURS = 24
QUICK_MAX_HOURS = 48


def score_story(source_diversity: int, authority: float, hours_old: float, discussion_velocity: float) -> float:
    recency = max(0.0, 1.0 - min(hours_old / 48.0, 1.0))
    return (
        0.35 * authority
        + 0.30 * min(source_diversity / 10.0, 1.0)
        + 0.25 * recency
        + 0.10 * min(discussion_velocity / 100.0, 1.0)
    )


def momentum(previous_score: float, current_score: float, new_sources: int) -> float:
    return (current_score - previous_score) + min(new_sources / 10.0, 0.5)


def apply_retention_tier(story: Story, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    age = now - story.first_seen_at
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
    now = now or datetime.now(timezone.utc)
    return first_seen_at >= (now - timedelta(minutes=30))
