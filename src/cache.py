"""Small disk-backed TTL cache for slow upstreams (Wikipedia, OpenSanctions).

Why bother? Both lookups happen once per *candidate name*, but reverse search
often surfaces the same celebrity (Einstein, Musk, etc.) across many uploads
within a session. A 24-hour cache cuts those round-trips and respects
Wikipedia's rate-limit etiquette.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("cache")


class TTLDiskCache:
    """JSON-on-disk TTL cache — async-safe, no external deps."""

    def __init__(self, root: str, ttl_seconds: int = 24 * 3600):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self._lock = asyncio.Lock()

    def _path(self, namespace: str, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:120]
        ns_dir = self.root / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{safe}.json"

    async def get(self, namespace: str, key: str) -> Optional[Any]:
        p = self._path(namespace, key)
        if not p.exists():
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"cache read failed for {namespace}/{key}: {e}")
            return None
        if time.time() - payload.get("ts", 0) > self.ttl:
            try:
                p.unlink()
            except OSError:
                pass
            return None
        return payload.get("value")

    async def set(self, namespace: str, key: str, value: Any) -> None:
        p = self._path(namespace, key)
        try:
            p.write_text(json.dumps({"ts": time.time(), "value": value}, default=str),
                         encoding="utf-8")
        except Exception as e:
            logger.warning(f"cache write failed for {namespace}/{key}: {e}")

    async def get_or_compute(
        self,
        namespace: str,
        key: str,
        producer: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Lookup, otherwise compute and store. ``producer`` is awaited."""
        hit = await self.get(namespace, key)
        if hit is not None:
            return hit
        async with self._lock:
            # Double-check after acquiring the lock.
            hit = await self.get(namespace, key)
            if hit is not None:
                return hit
            value = await producer()
            if value is not None:
                await self.set(namespace, key, value)
            return value
