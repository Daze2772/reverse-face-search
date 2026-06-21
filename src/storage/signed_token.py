"""HMAC-signed token helpers for serving private images via a public URL.

Why:
    MinIO is private. We need a public URL to give to Yandex/Google/Bing so
    they can fetch the reference image. The naive approach is to expose
    MinIO directly with a presigned S3 URL, but that:
      - leaks a new public domain (bot-detection risk),
      - requires another HTTPS cert,
      - and can't be locked down behind the same ingress as the API.

    Instead, we issue a short-lived HMAC-signed token that only the project's
    own backend can verify. The token embeds a key (an object name in MinIO
    or a filename on local disk) and an expiry timestamp. The engines fetch
    ``/api/img/{token}`` from the same domain as the API; the backend
    validates the signature and streams bytes back from storage.

    Tokens are stateless — no DB lookup, no replay table — so they scale to
    millions of requests trivially.
"""

import base64
import hmac
import hashlib
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger("storage.signed_token")

# 10 minutes is plenty: engines typically fetch the URL within 30 s of
# receiving it, and the token can be refused if a search is replayed later.
DEFAULT_TTL_SECONDS = 600


def _secret() -> bytes:
    secret = os.environ.get("RFS_IMG_TOKEN_SECRET", "").strip()
    if not secret:
        # In production, refuse to boot rather than silently use a weak key.
        # In dev, fall back to a fixed string so unit tests run.
        if os.environ.get("RFS_ENV") == "production":
            raise RuntimeError(
                "RFS_IMG_TOKEN_SECRET must be set in production "
                "(generate with: openssl rand -hex 32)"
            )
        secret = "dev-only-do-not-use-in-prod-bf9d2c1a"
    return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Issue a signed token for object/file ``key``.

    Returned format: ``<b64url(key)>.<exp>.<sig>``  (URL-safe, no slashes).
    Length: ~110 chars for a UUID + ext.
    """
    exp = int(time.time() + max(1, ttl_seconds))
    key_part = _b64url_encode(key.encode("utf-8"))
    msg = f"{key_part}.{exp}".encode("utf-8")
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return f"{key_part}.{exp}.{sig}"


def verify_token(token: str) -> Optional[Tuple[str, int]]:
    """Validate a token. Returns ``(key, expiry)`` or ``None``.

    Constant-time signature comparison; expiry checked last so the timing
    side-channel only leaks "valid signature, expired" vs "invalid signature".
    """
    if not token or token.count(".") != 2:
        return None

    key_part, exp_str, sig = token.split(".", 2)
    try:
        exp = int(exp_str)
    except ValueError:
        return None

    msg = f"{key_part}.{exp}".encode("utf-8")
    expected = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        logger.debug("Signed token signature mismatch")
        return None

    if exp < int(time.time()):
        logger.debug(f"Signed token expired ({exp} < now)")
        return None

    try:
        key = _b64url_decode(key_part).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return key, exp
