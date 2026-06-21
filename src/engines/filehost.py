"""Temporary file hosting — gives the reverse-image engines a public URL.

Strategy (highest privacy first):

1. **Signed proxy** (default, no external dependency)
   The uploaded image stays in our storage (MinIO in prod, local disk in
   dev). The engines get ``{RFS_PUBLIC_URL}/api/img/{token}`` — a short-
   lived HMAC-signed URL on the project's own ingress. Image never leaves
   your infrastructure. Solves MinIO's "needs public domain" downside.

2. **imgbb** (fallback when signed proxy is unreachable)
   Used only when the engine pipeline detects Google has rejected the
   signed URL (rare; ``RFS_FORCE_IMGBB=true`` to force).

3. **tmpfiles.org** (legacy, anonymous)

4. **0x0.st** (last resort)

The first-pass policy lives in :func:`upload_to_public`. Engines may call
``upload_to_public(path, prefer_external=True)`` to skip directly to imgbb
when retrying after a 0-result signed-proxy attempt.
"""

import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple

import httpx

from ..storage import get_storage, make_token

logger = logging.getLogger("filehost")

IMGBB_URL = "https://api.imgbb.com/1/upload"
TMPFILES_URL = "https://tmpfiles.org/api/v1/upload"
ZEROXZERO_URL = "https://0x0.st"


# Public URL of the running app — set via env. When empty, the signed proxy
# strategy is skipped (we can't form a public URL without knowing where the
# app is reachable from the internet).
def _public_base_url() -> str:
    return os.environ.get("RFS_PUBLIC_URL", "").rstrip("/")


async def upload_to_public(
    image_path: str,
    timeout: int = 30,
    prefer_external: bool = False,
) -> Optional[str]:
    """Upload the image to a public host and return a direct-fetchable URL.

    ``prefer_external=True`` skips the privacy-preserving signed proxy and
    goes straight to imgbb. Used by the engine layer when a signed-proxy
    retry returns 0 results (i.e. the engine refused to crawl our domain).
    """
    path = Path(image_path)
    if not path.exists():
        logger.error(f"Image not found: {image_path}")
        return None

    force_external = os.environ.get("RFS_FORCE_IMGBB", "false").lower() in ("1", "true", "yes")
    chain = (
        [_upload_imgbb, _upload_tmpfiles, _upload_zeroxzero]
        if (prefer_external or force_external)
        else [_signed_proxy_url, _upload_imgbb, _upload_tmpfiles, _upload_zeroxzero]
    )

    for fn in chain:
        try:
            url = await fn(path, timeout)
            if url:
                logger.info(f"{fn.__name__} → {url[:80]}...")
                return url
        except Exception as e:
            logger.warning(f"{fn.__name__} failed: {e}")

    logger.error("All file hosts failed — engines will have no public URL to use")
    return None


# ─── Signed proxy ──────────────────────────────────────────────────────────


async def _signed_proxy_url(path: Path, timeout: int) -> Optional[str]:
    """Save the image to storage and return a signed proxy URL.

    The bytes never go to a third party. The token's TTL caps replay risk.
    """
    base = _public_base_url()
    if not base:
        logger.debug("RFS_PUBLIC_URL not configured; skipping signed proxy")
        return None

    storage = get_storage(os.environ.get("RFS_UPLOAD_DIR", "uploads"))
    # Key: <uuid_filename>.<ext> derived from the on-disk temp file. The
    # FastAPI upload endpoint already persists the file with a uuid name.
    key = path.name
    content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"

    # If LocalStorage and the file is already at root, this is a no-op write
    # (same bytes). If MinIOStorage, this puts the bytes into the bucket.
    try:
        if not storage.exists(key):
            storage.save(key, path.read_bytes(), content_type=content_type)
    except Exception as e:
        logger.warning(f"signed-proxy storage save failed: {e}")
        return None

    ttl = int(os.environ.get("RFS_IMG_TOKEN_TTL_SECONDS", "600"))
    token = make_token(key, ttl_seconds=ttl)
    return f"{base}/api/img/{token}"


# ─── External hosts ────────────────────────────────────────────────────────


async def _upload_imgbb(path: Path, timeout: int) -> Optional[str]:
    """Upload to imgbb (requires IMGBB_API_KEY). Returns the direct image URL."""
    api_key = os.environ.get("IMGBB_API_KEY", "").strip()
    if not api_key:
        return None

    async with httpx.AsyncClient(timeout=timeout) as client:
        with open(path, "rb") as f:
            response = await client.post(
                IMGBB_URL,
                params={"key": api_key, "expiration": 3600},
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
