from app.services.feed_service import _select_story_sources


def test_select_story_sources_enforces_diversity_and_per_source_cap() -> None:
    candidates = [
        {"source_id": 1, "source_name": "S1", "url": "u1", "score": 0.99},
        {"source_id": 1, "source_name": "S1", "url": "u2", "score": 0.95},
        {"source_id": 1, "source_name": "S1", "url": "u3", "score": 0.92},
        {"source_id": 2, "source_name": "S2", "url": "u4", "score": 0.90},
        {"source_id": 2, "source_name": "S2", "url": "u5", "score": 0.88},
        {"source_id": 3, "source_name": "S3", "url": "u6", "score": 0.87},
        {"source_id": 4, "source_name": "S4", "url": "u7", "score": 0.86},
    ]

    selected = _select_story_sources(candidates, max_total=6, max_per_source=2, min_unique_target=3)

    assert len(selected) == 6
    counts = {}
    for item in selected:
        counts[item.source_name] = counts.get(item.source_name, 0) + 1

    assert counts["S1"] <= 2
    assert counts["S2"] <= 2
    assert len(counts) >= 3
