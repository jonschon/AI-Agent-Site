from datetime import datetime, timedelta, timezone

from app.services.scoring import badges_for_story, is_new_story, score_story


def test_score_story_range() -> None:
    score = score_story(source_diversity=5, authority=0.8, hours_old=2, discussion_velocity=20)
    assert 0 <= score <= 1.2


def test_badges() -> None:
    badges = badges_for_story(is_new=True, momentum_score=0.4, new_sources=3, updated_recently=True)
    assert "NEW" in badges
    assert "Trending" in badges
    assert "+3 sources" in badges
    assert "Updated" in badges


def test_is_new_story() -> None:
    now = datetime.now(timezone.utc)
    assert is_new_story(now - timedelta(minutes=10), now)
    assert not is_new_story(now - timedelta(hours=2), now)
