from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _deterministic_embedding(text: str, dimensions: int = 16) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [int(digest[i]) / 255 for i in range(dimensions)]


def _fallback_summary(headline_seed: str, snippets: list[str], max_bullets: int = 3) -> tuple[str, list[str]]:
    max_bullets = max(1, min(max_bullets, 3))
    headline = headline_seed.strip()[:120]
    bullets = []
    for snippet in snippets[:max_bullets]:
        cleaned = " ".join(snippet.split())[:140]
        bullets.append(cleaned if cleaned else "Update available from monitored sources.")
    while len(bullets) < 1:
        bullets.append("Coverage is evolving as additional sources publish.")
    return headline, bullets[:max_bullets]


def _extract_output_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    outputs = payload.get("output") or []
    chunks: list[str] = []
    for item in outputs:
        content_list = item.get("content") or []
        for content in content_list:
            text_value = content.get("text")
            if isinstance(text_value, str):
                chunks.append(text_value)
    return "\n".join(chunks).strip()


def _post_openai(path: str, payload: dict) -> dict:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    base_url = settings.openai_base_url.rstrip("/")
    url = f"{base_url}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=settings.openai_timeout_seconds) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def generate_embedding(text: str, dimensions: int = 16) -> list[float]:
    if not settings.openai_api_key:
        return _deterministic_embedding(text, dimensions=dimensions)

    try:
        payload: dict = {
            "model": settings.embedding_model,
            "input": text[:12000],
            "encoding_format": "float",
        }
        if settings.openai_embedding_dimensions:
            payload["dimensions"] = settings.openai_embedding_dimensions

        data = _post_openai("/embeddings", payload)
        embedding = data["data"][0]["embedding"]
        if isinstance(embedding, list) and embedding:
            return [float(v) for v in embedding]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Embedding request failed, falling back to deterministic embedding: %s", exc)

    return _deterministic_embedding(text, dimensions=dimensions)


def summarize_story(headline_seed: str, snippets: list[str], max_bullets: int = 3) -> tuple[str, list[str]]:
    max_bullets = max(1, min(max_bullets, 3))
    fallback_headline, fallback_bullets = _fallback_summary(headline_seed, snippets, max_bullets=max_bullets)
    if not settings.openai_api_key:
        return fallback_headline, fallback_bullets

    prompt = (
        "Summarize this AI ecosystem news story.\n"
        "Return JSON with keys: headline, bullets.\n"
        "Requirements:\n"
        "- headline: concise, factual, <= 120 chars\n"
        f"- bullets: array of 1 to {max_bullets} concise bullets, each <= 140 chars\n"
        "- avoid speculation and marketing language\n\n"
        f"Headline seed: {headline_seed}\n"
        "Snippets:\n"
        + "\n".join(f"- {snippet[:350]}" for snippet in snippets[:6] if snippet.strip())
    )

    payload = {
        "model": settings.summary_model,
        "input": [
            {
                "role": "system",
                "content": "You are a precise newsroom summarization assistant.",
            },
            {"role": "user", "content": prompt},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "story_summary",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": max_bullets,
                        },
                    },
                    "required": ["headline", "bullets"],
                    "additionalProperties": False,
                },
            }
        },
        "max_output_tokens": 300,
    }

    try:
        response = _post_openai("/responses", payload)
        raw_text = _extract_output_text(response)
        parsed = json.loads(raw_text)
        headline = str(parsed.get("headline", "")).strip()[:120] or fallback_headline
        raw_bullets = parsed.get("bullets") or []
        bullets = [str(item).strip()[:140] for item in raw_bullets if str(item).strip()]
        if not bullets:
            bullets = fallback_bullets
        return headline, bullets[:max_bullets]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Summary request failed, falling back to local summary: %s", exc)
        return fallback_headline, fallback_bullets


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
