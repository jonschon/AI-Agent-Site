from __future__ import annotations

import hashlib
from datetime import datetime


def generate_embedding(text: str, dimensions: int = 16) -> list[float]:
    # Deterministic pseudo-embedding for MVP scaffolding; replace with provider call in prod.
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [int(digest[i]) / 255 for i in range(dimensions)]
    return values


def summarize_story(headline_seed: str, snippets: list[str]) -> tuple[str, list[str]]:
    headline = headline_seed.strip()[:120]
    bullets = []
    for snippet in snippets[:3]:
        cleaned = " ".join(snippet.split())[:140]
        bullets.append(cleaned if cleaned else "Update available from monitored sources.")
    while len(bullets) < 3:
        bullets.append("Coverage is evolving as additional sources publish.")
    return headline, bullets[:3]


def infer_tags(text: str) -> list[str]:
    lower = text.lower()
    tags = []
    mapping = {
        "model": "Models",
        "startup": "Startups",
        "agent": "Agents",
        "research": "Research",
        "infra": "Infrastructure",
        "gpu": "Infrastructure",
    }
    for key, value in mapping.items():
        if key in lower and value not in tags:
            tags.append(value)
    if not tags:
        tags.append("Research")
    return tags


def now_iso() -> str:
    return datetime.utcnow().isoformat()
