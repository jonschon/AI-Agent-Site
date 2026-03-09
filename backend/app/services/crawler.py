from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime, timezone
from time import struct_time
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import feedparser
import httpx

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


def _extract_first_img_src(html: str) -> Optional[str]:
    if not html:
        return None
    match = re.search(r"""<img[^>]+src=["']([^"']+)["']""", html, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def extract_image_url(entry: dict) -> Optional[str]:
    media_content = entry.get("media_content")
    if isinstance(media_content, list):
        for item in media_content:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()

    media_thumbnail = entry.get("media_thumbnail")
    if isinstance(media_thumbnail, list):
        for item in media_thumbnail:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url.strip():
                    return url.strip()

    links = entry.get("links")
    if isinstance(links, list):
        for item in links:
            if not isinstance(item, dict):
                continue
            href = item.get("href")
            link_type = (item.get("type") or "").lower()
            if isinstance(href, str) and href.strip() and link_type.startswith("image/"):
                return href.strip()

    if isinstance(entry.get("image"), dict):
        href = entry["image"].get("href")
        if isinstance(href, str) and href.strip():
            return href.strip()

    content_items = entry.get("content")
    if isinstance(content_items, list):
        for content in content_items:
            if not isinstance(content, dict):
                continue
            value = content.get("value")
            if isinstance(value, str):
                img = _extract_first_img_src(value)
                if img:
                    return img

    summary = entry.get("summary") or entry.get("description") or ""
    if isinstance(summary, str):
        img = _extract_first_img_src(summary)
        if img:
            return img

    return None


def fetch_article_image_url(url: str) -> Optional[str]:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AI-News-Bot/1.0; +https://example.com/bot)"}
    try:
        response = httpx.get(url, headers=headers, timeout=1.5, follow_redirects=True)
    except Exception:  # noqa: BLE001
        return None
    if response.status_code >= 400:
        return None
    html = response.text or ""
    if not html:
        return None

    patterns = [
        re.compile(
            r"""<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["']""",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"""<meta[^>]+name=["']twitter:image(?::src)?["'][^>]+content=["']([^"']+)["']""",
            flags=re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if not match:
            continue
        image_url = (match.group(1) or "").strip()
        if not image_url:
            continue
        if image_url.startswith("data:"):
            continue
        if image_url.startswith("//"):
            return f"https:{image_url}"
        if image_url.startswith("/"):
            return urljoin(url, image_url)
        return image_url
    return None


def fetch_feed_entries(source: Source, limit: int = 20) -> list[dict]:
    config = source.crawl_config_json or {}
    feed_urls = config.get("feed_urls") or []
    if not isinstance(feed_urls, list):
        return []

    entries: list[dict] = []
    article_image_fetches = 0
    max_article_image_fetches = 2
    for feed_url in feed_urls:
        parsed = feedparser.parse(feed_url)
        for item in parsed.entries[:limit]:
            url = item.get("link")
            if not url:
                continue
            canonical_url = canonicalize_url(url)
            text = extract_text(item)
            published = _to_datetime(item.get("published_parsed") or item.get("updated_parsed"))
            image_url = extract_image_url(item)
            if not image_url and article_image_fetches < max_article_image_fetches:
                image_url = fetch_article_image_url(url)
                article_image_fetches += 1
            entries.append(
                {
                    "url": canonical_url,
                    "title": (item.get("title") or "Untitled")[:300],
                    "content": text,
                    "image_url": image_url,
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
        "image_url": None,
        "published_at": now.isoformat(),
        "fingerprint": hashlib.sha256(title.encode("utf-8")).hexdigest(),
        "feed_url": None,
    }
