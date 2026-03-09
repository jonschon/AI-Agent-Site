from __future__ import annotations

import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from datetime import datetime

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RELEVANCE_KEYWORDS = (
    "ai",
    "agent",
    "agentic",
    "model",
    "llm",
    "inference",
    "gpu",
    "chip",
    "cloud",
    "api",
    "developer",
    "platform",
    "software",
    "data",
    "security",
    "infrastructure",
    "research",
    "technology",
    "tech",
)


def _deterministic_embedding(text: str, dimensions: int = 16) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [int(digest[i]) / 255 for i in range(dimensions)]


def _fallback_summary(headline_seed: str, snippets: list[str], max_bullets: int = 3) -> tuple[str, list[str]]:
    max_bullets = max(1, min(max_bullets, 3))
    headline = headline_seed.strip()[:120]
    bullets: list[str] = []
    for snippet in snippets[:max_bullets]:
        cleaned = " ".join(snippet.split())[:220]
        bullets.append(cleaned if cleaned else "Update available from monitored sources.")
    return headline, _sanitize_bullets(headline, bullets, snippets, max_bullets=max_bullets)


def _normalize_for_compare(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _near_duplicate(a: str, b: str, threshold: float = 0.78) -> bool:
    na = _normalize_for_compare(a)
    nb = _normalize_for_compare(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def _sanitize_bullets(headline: str, bullets: list[str], snippets: list[str], max_bullets: int) -> list[str]:
    out: list[str] = []
    for bullet in bullets:
        cleaned = " ".join(bullet.split())[:220]
        if not cleaned:
            continue
        if _near_duplicate(cleaned, headline):
            continue
        if any(_near_duplicate(cleaned, existing) for existing in out):
            continue
        out.append(cleaned)
        if len(out) >= max_bullets:
            break

    if not out:
        for snippet in snippets:
            cleaned = " ".join(snippet.split())[:220]
            if not cleaned or _near_duplicate(cleaned, headline):
                continue
            out.append(cleaned)
            break

    if not out:
        out.append("Coverage is evolving as additional sources publish.")
    return _ensure_relevance_bullet(headline, out[:max_bullets], snippets, max_bullets=max_bullets)


def _contains_relevance_signal(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in RELEVANCE_KEYWORDS)


def _ensure_relevance_bullet(headline: str, bullets: list[str], snippets: list[str], max_bullets: int) -> list[str]:
    if any(_contains_relevance_signal(bullet) for bullet in bullets):
        return bullets[:max_bullets]

    for snippet in snippets:
        cleaned = " ".join(snippet.split())[:220]
        if not cleaned:
            continue
        if not _contains_relevance_signal(cleaned):
            continue
        if any(_near_duplicate(cleaned, existing) for existing in bullets):
            continue
        candidate = cleaned
        break
    else:
        candidate = f"Tech relevance: {headline.strip()[:170]}."

    if len(bullets) < max_bullets:
        bullets.append(candidate)
        return bullets[:max_bullets]

    bullets[-1] = candidate
    return bullets[:max_bullets]


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
        f"- bullets: array of 1 to {max_bullets} concise bullets, each <= 220 chars\n"
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
        bullets = [str(item).strip()[:220] for item in raw_bullets if str(item).strip()]
        if not bullets:
            bullets = fallback_bullets
        bullets = _sanitize_bullets(headline, bullets, snippets, max_bullets=max_bullets)
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
