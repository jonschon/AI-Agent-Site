from app.services.cluster import (
    cluster_confidence,
    cosine_similarity,
    lexical_overlap,
    overlap_ratio,
    tokenize,
)


def test_tokenize_basic() -> None:
    tokens = tokenize("OpenAI launches Agent SDK v2")
    assert "openai" in tokens
    assert "agent" in tokens


def test_overlap_ratio() -> None:
    assert overlap_ratio(["openai", "agents"], ["openai", "models"]) == 1 / 3


def test_confidence_monotonic() -> None:
    high = cluster_confidence(semantic=0.9, lexical=0.5, entity_overlap=0.5)
    low = cluster_confidence(semantic=0.2, lexical=0.1, entity_overlap=0.1)
    assert high > low


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) > 0.99
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) < 0.01


def test_lexical_overlap() -> None:
    assert lexical_overlap(["openai", "agent"], ["openai", "sdk"]) == 1 / 3
