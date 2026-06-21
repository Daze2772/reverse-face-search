"""Temporary file hosting — upload to public host for reverse search URL."""

import logging
import httpx
from pathlib import Path
from typing import Optional

logger = logging.getLogger("filehost")

# 0x0.st — anonymous file host, no API key required
HOSTS = [
    "https://0x0.st",
    "https://tmpfiles.org/api/v1/upload",  # fallback
]


async def upload_to_public(image_path: str, timeout: int = 30) -> Optional[str]:
    """Upload image to a public temp host and return the URL.
    
    Tries 0x0.st first (anonymous, no auth), falls back to alternatives.
    """
    path = Path(image_path)
    if not path.exists():
        logger.error(f"Image not found: {image_path}")
        return None

    # Try 0x0.st first — simple curl-style upload
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(path, "rb") as f:
                response = await client.post(
                    "https://0x0.st",
                    files={"file": (path.name, f, "application/octet-stream")},
                )
            if response.status_code == 200:
                url = response.text.strip()
                if url.startswith("http"):
                    logger.info(f"Uploaded to 0x0.st: {url}")
                    return url
            logger.warning(f"0x0.st returned {response.status_code}: {response.text[:200]}")
    except Exception as e:
        logger.warning(f"0x0.st upload failed: {e}")

    # Fallback: tmpfiles.org
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(path, "rb") as f:
                response = await client.post(
                    "https://tmpfiles.org/api/v1/upload",
                    files={"file": (path.name, f, "application/octet-stream")},
                )
            if response.status_code == 200:
                data = response.json()
                url = data.get("data", {}).get("url", "")
                if url:
                    # tmpfiles.org URLs need /dl/ appended for direct download
                    url = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    logger.info(f"Uploaded to tmpfiles.org: {url}")
                    return url
    except Exception as e:
        logger.warning(f"tmpfiles.org upload failed: {e}")

    # Final fallback: use file.io
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            with open(path, "rb") as f:
                response = await client.post(
                    "https://file.io",
                    files={"file": (path.name, f, "application/octet-stream")},
                )
            if response.status_code == 200:
                data = response.json()
                url = data.get("link", "")
                if url:
                    logger.info(f"Uploaded to file.io: {url}")
                    return url
    except Exception as e:
        logger.warning(f"file.io upload failed: {e}")

    logger.error("All file hosts failed — cannot get public URL for reverse search")
    return None
