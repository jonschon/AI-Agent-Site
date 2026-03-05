from __future__ import annotations

import calendar
import hashlib
from datetime import datetime, timezone
from time import struct_time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser

from app.models.news import Source


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query_items = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    normalized = parsed._replace(
        scheme=(parsed.scheme or "https").lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(query_items),
        fragment="",
    )
    return urlunparse(normalized)


def _to_datetime(value: object) -> datetime:
    if isinstance(value, struct_time):
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return datetime.now(timezone.utc)


def extract_text(entry: dict) -> str:
    summary = entry.get("summary") or entry.get("description") or ""
    title = entry.get("title") or ""
    content_items = entry.get("content") or []
    body = ""
    if isinstance(content_items, list) and content_items:
        first = content_items[0]
        if isinstance(first, dict):
            body = first.get("value", "")
    text = " ".join(part for part in [title, summary, body] if part)
    return " ".join(text.split())[:4000]


def fetch_feed_entries(source: Source, limit: int = 20) -> list[dict]:
    config = source.crawl_config_json or {}
    feed_urls = config.get("feed_urls") or []
    if not isinstance(feed_urls, list):
        return []

    entries: list[dict] = []
    for feed_url in feed_urls:
        parsed = feedparser.parse(feed_url)
        for item in parsed.entries[:limit]:
            url = item.get("link")
            if not url:
                continue
            canonical_url = canonicalize_url(url)
            text = extract_text(item)
            published = _to_datetime(item.get("published_parsed") or item.get("updated_parsed"))
            entries.append(
                {
                    "url": canonical_url,
                    "title": (item.get("title") or "Untitled")[:300],
                    "content": text,
                    "published_at": published.isoformat(),
                    "fingerprint": hashlib.sha256((canonical_url + text[:500]).encode("utf-8")).hexdigest(),
                    "feed_url": feed_url,
                }
            )
    return entries


def build_synthetic_entry(source: Source) -> dict:
    now = datetime.now(timezone.utc)
    title = f"{source.name} AI update {now.strftime('%H:%M')}"
    url_hash = hashlib.sha1(f"{source.domain}-{title}".encode("utf-8")).hexdigest()[:10]
    return {
        "url": f"https://{source.domain}/news/{url_hash}",
        "title": title,
        "content": title,
        "published_at": now.isoformat(),
        "fingerprint": hashlib.sha256(title.encode("utf-8")).hexdigest(),
        "feed_url": None,
    }
