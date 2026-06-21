"""Result-page image extraction for face-embedding verification.

When a reverse-image-search engine returns a URL, that URL points to a
*page* — not a face image. For InsightFace to filter false positives we
need the page's main image. The cheapest, most reliable place to grab it
is from the page's Open Graph / Twitter Card metadata.

This module fetches the HTML head of each result page in parallel,
extracts the best candidate image URL, and returns ``[(page_url, image_url)]``
pairs ready for :class:`~src.face.embedding.FaceVerifier`.

Downside mitigation:
    * Concurrency is bounded by a semaphore (8 in flight) so we don't
      fan-out 50 simultaneous HTTPS handshakes.
    * Each request has a 5-second cap; slow pages are dropped, not blocking.
    * We download only the first 64 KB of HTML — long enough to capture the
      ``<head>`` of any well-formed page, short enough that one rogue page
      can't tie us up downloading megabytes of HTML.
"""

import asyncio
import logging
import re
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

logger = logging.getLogger("face.page_extract")


# Match <meta property="og:image" content="..."> or twitter:image variants.
_META_PATTERNS = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']', re.IGNORECASE),
    re.compile(r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']', re.IGNORECASE),
]

DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


async def extract_preview_images(
    page_urls: Iterable[str],
    max_concurrent: int = 8,
    per_request_timeout: float = 5.0,
    max_html_bytes: int = 64 * 1024,
) -> List[Tuple[str, str]]:
    """Return ``[(page_url, og_image_url), ...]`` for every page we can read.

    Pages without an og:image / twitter:image are silently skipped.
    """
    sem = asyncio.Semaphore(max_concurrent)
    limits = httpx.Limits(max_keepalive_connections=max_concurrent, max_connections=max_concurrent * 2)

    async with httpx.AsyncClient(
        timeout=per_request_timeout,
        follow_redirects=True,
        headers=DEFAULT_HEADERS,
        limits=limits,
    ) as client:
        tasks = [
            asyncio.create_task(_one(client, sem, url, max_html_bytes))
            for url in page_urls
        ]
        out: List[Tuple[str, str]] = []
        for coro in asyncio.as_completed(tasks):
            pair = await coro
            if pair is not None:
                out.append(pair)
        return out


async def _one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    url: str,
    max_html_bytes: int,
) -> Optional[Tuple[str, str]]:
    async with sem:
        try:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                # Read just enough HTML to cover <head>.
                buf = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    buf.extend(chunk)
                    if len(buf) >= max_html_bytes:
                        break
                html = buf.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"og:image fetch failed for {url}: {e}")
            return None

    img_url = _find_image_in_head(html)
    if not img_url:
        return None
    return url, urljoin(url, img_url)


def _find_image_in_head(html: str) -> Optional[str]:
    """Search HTML head for the first og:image / twitter:image match."""
    # Trim to <head>...</head> for speed and to avoid matching <body> noise.
    head_end = html.lower().find("</head>")
    snippet = html if head_end == -1 else html[:head_end]

    for pat in _META_PATTERNS:
        m = pat.search(snippet)
        if m:
            return m.group(1).strip()
    return None
