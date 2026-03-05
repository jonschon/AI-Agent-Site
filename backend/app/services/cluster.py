from __future__ import annotations

import math
from collections import Counter


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=True))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def lexical_overlap(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    return len(set_a & set_b) / len(set_a | set_b)


def cluster_confidence(semantic: float, lexical: float, entity_overlap: float) -> float:
    return (0.6 * semantic) + (0.25 * lexical) + (0.15 * entity_overlap)


def extract_entities(tokens: list[str]) -> list[str]:
    counts = Counter(token for token in tokens if token[:1].isupper() and len(token) > 2)
    return [entity for entity, _ in counts.most_common(8)]
