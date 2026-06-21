"""Temporary file hosting — upload to public host so the search engines can fetch it.

Order of preference:
1. imgbb (requires IMGBB_API_KEY) — most reliable, what Google Lens prefers.
2. tmpfiles.org — anonymous, no API key, decent uptime.
3. 0x0.st — anonymous, frequently blocks AI bots; last resort.
"""

import logging
import os
import asyncio
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("filehost")

IMGBB_URL = "https://api.imgbb.com/1/upload"
TMPFILES_URL = "https://tmpfiles.org/api/v1/upload"
ZEROXZERO_URL = "https://0x0.st"


async def upload_to_public(image_path: str, timeout: int = 30) -> Optional[str]:
    """Upload the image to a public host and return a direct-fetchable URL.

    Uses :env:`IMGBB_API_KEY` when available; otherwise falls back through
    tmpfiles.org and 0x0.st. Returns ``None`` only when every host fails.
    """
    path = Path(image_path)
    if not path.exists():
        logger.error(f"Image not found: {image_path}")
        return None

    for fn in (_upload_imgbb, _upload_tmpfiles, _upload_zeroxzero):
        try:
            url = await fn(path, timeout)
            if url:
                logger.info(f"{fn.__name__} → {url}")
                return url
        except Exception as e:
            logger.warning(f"{fn.__name__} failed: {e}")

    logger.error("All file hosts failed — engines will have no public URL to use")
    return None


async def _upload_imgbb(path: Path, timeout: int) -> Optional[str]:
    """Upload to imgbb (requires IMGBB_API_KEY). Returns the direct image URL."""
    api_key = os.environ.get("IMGBB_API_KEY", "").strip()
    if not api_key:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(path, "rb") as f:
            response = await client.post(
                IMGBB_URL,
                params={"key": api_key, "expiration": 3600},  # auto-purge in 1 hour
                files={"image": (path.name, f, "application/octet-stream")},
            )
        if response.status_code != 200:
            logger.warning(f"imgbb returned {response.status_code}: {response.text[:200]}")
            return None
        data = response.json()
        if not data.get("success"):
            logger.warning(f"imgbb: {data.get('error', {}).get('message', 'unknown error')}")
            return None
        return data.get("data", {}).get("url")


async def _upload_tmpfiles(path: Path, timeout: int) -> Optional[str]:
    """Upload to tmpfiles.org. URL gets rewritten to /dl/ for direct download."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(path, "rb") as f:
            response = await client.post(
                TMPFILES_URL,
                files={"file": (path.name, f, "application/octet-stream")},
            )
        if response.status_code != 200:
            return None
        data = response.json()
        url = data.get("data", {}).get("url", "")
        if url:
            return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
        return None


async def _upload_zeroxzero(path: Path, timeout: int) -> Optional[str]:
    """Upload to 0x0.st. The service is anti-bot and may reject AI-shaped clients."""
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "curl/8"}) as client:
        with open(path, "rb") as f:
            response = await client.post(
                ZEROXZERO_URL,
                files={"file": (path.name, f, "application/octet-stream")},
            )
        if response.status_code != 200:
            return None
        text = response.text.strip()
        return text if text.startswith("http") else None
