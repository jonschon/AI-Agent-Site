from datetime import datetime, timedelta, timezone

from app.services.scoring import badges_for_story, is_new_story, score_story


def test_score_story_range() -> None:
    score = score_story(
        source_diversity=5,
        authority=0.8,
        hours_old=2,
        discussion_velocity=20,
        entity_weight=0.7,
    )
    assert 0 <= score <= 1.0


def test_score_story_respects_weights() -> None:
    authority_heavy = score_story(
        source_diversity=1,
        authority=1.0,
        hours_old=20,
        discussion_velocity=0,
        entity_weight=0.0,
        w_authority=0.8,
        w_diversity=0.05,
        w_recency=0.05,
        w_discussion=0.05,
        w_entity=0.05,
    )
    diversity_heavy = score_story(
        source_diversity=10,
        authority=0.2,
        hours_old=20,
        discussion_velocity=0,
        entity_weight=0.0,
        w_authority=0.05,
        w_diversity=0.8,
        w_recency=0.05,
        w_discussion=0.05,
        w_entity=0.05,
    )
    assert diversity_heavy > authority_heavy


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
