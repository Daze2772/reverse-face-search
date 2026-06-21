"""Active name-based social search.

When reverse-image-search yields a candidate person name but few/no social
URLs (e.g. private-ish individuals, photographers, niche academics), this
module actively queries DuckDuckGo with ``site:`` filters to look for that
name on the major platforms. The results feed back into username extraction.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urlparse

import httpx

logger = logging.getLogger("extract.name_search")


# DuckDuckGo HTML endpoint — returns plain HTML, no JS required.
DUCK_URL = "https://html.duckduckgo.com/html/"

PLATFORM_SITES = {
    "instagram": "instagram.com",
    "linkedin": "linkedin.com/in",
    "twitter": "twitter.com",
    "x":        "x.com",
    "facebook": "facebook.com",
    "tiktok":   "tiktok.com",
    "github":   "github.com",
    "youtube":  "youtube.com",
    "reddit":   "reddit.com",
    "medium":   "medium.com",
}


LINK_PATTERN = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', re.IGNORECASE)
REDIRECT_PARAM = re.compile(r'[?&]uddg=([^&]+)')


async def search_socials_by_name(
    name: str,
    platforms: Optional[List[str]] = None,
    timeout: int = 15,
    per_platform_limit: int = 3,
) -> Dict[str, List[Dict[str, str]]]:
    """Search DuckDuckGo for ``name`` on each social platform.

    Returns a dict ``{platform: [{url, title}, ...]}``.
    """
    target = platforms or list(PLATFORM_SITES.keys())
    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    }

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        results: Dict[str, List[Dict[str, str]]] = {}
        tasks = [
            _search_one(client, name, p, PLATFORM_SITES[p], per_platform_limit)
            for p in target if p in PLATFORM_SITES
        ]
        for platform, hits in await asyncio.gather(*tasks, return_exceptions=False):
            if hits:
                results[platform] = hits

    total = sum(len(v) for v in results.values())
    logger.info(f"Active name search '{name}': {total} hits across {len(results)} platforms")
    return results


async def _search_one(
    client: httpx.AsyncClient,
    name: str,
    platform: str,
    site: str,
    limit: int,
) -> tuple[str, List[Dict[str, str]]]:
    query = f'"{name}" site:{site}'
    try:
        resp = await client.post(DUCK_URL, data={"q": query, "kl": "us-en"})
        if resp.status_code != 200:
            return platform, []
        hits: List[Dict[str, str]] = []
        for match in LINK_PATTERN.finditer(resp.text):
            url = _unwrap_duck(match.group(1))
            if not url or site not in url:
                continue
            if any(h["url"] == url for h in hits):
                continue
            hits.append({"url": url, "title": "", "snippet": "", "source": "name_search"})
            if len(hits) >= limit:
                break
        return platform, hits
    except Exception as e:
        logger.debug(f"name search {platform} failed: {e}")
        return platform, []


def _unwrap_duck(url: str) -> str:
    """DuckDuckGo wraps result URLs as ``/l/?uddg=<urlencoded>``."""
    if url.startswith("//"):
        url = "https:" + url
    m = REDIRECT_PARAM.search(url)
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    if url.startswith("http"):
        return url
    return ""
