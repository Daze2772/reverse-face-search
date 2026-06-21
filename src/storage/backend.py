"""Storage backends — abstracts where the uploaded image actually lives.

The pipeline doesn't care whether the image sits on local disk or in a MinIO
bucket. It just hands the storage layer ``(key, bytes)`` and asks for the
bytes back when the proxy endpoint serves them.

Two implementations:

* :class:`LocalStorage` — writes to the configured uploads directory. Used
  when ``MINIO_ENDPOINT`` is empty (dev / Emergent preview).
* :class:`MinIOStorage` — uses the MinIO Python client to put/get objects
  in a bucket. Used in production (docker-compose ships a minio service).

Both speak the same tiny interface; the rest of the codebase treats the
active backend as the single :func:`get_storage` singleton.
"""

import io
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("storage.backend")


class LocalStorage:
    """Filesystem-backed storage — used as the default and as a fallback."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, key: str) -> Optional[bytes]:
        path = self._path(key)
        if not path.exists():
            return None
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def _path(self, key: str) -> Path:
        # Reject path traversal — only filename component allowed.
        safe = Path(key).name
        return self.root / safe

    @property
    def name(self) -> str:
        return f"local({self.root})"


class MinIOStorage:
    """MinIO/S3-compatible object storage. Lazy-imports the SDK."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
        region: str = "us-east-1",
    ):
        try:
            from minio import Minio
            from minio.error import S3Error
        except ImportError as e:
            raise RuntimeError(
                "minio package not installed. Install with: pip install minio"
            ) from e
        self._S3Error = S3Error

        self.bucket = bucket
        self.client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        # Idempotent bucket creation.
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info(f"Created MinIO bucket: {bucket}")
            # Set bucket to private — we never want public read.
        except Exception as e:
            logger.error(f"MinIO bucket setup failed: {e}")
            raise

    def save(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        data = io.BytesIO(content)
        self.client.put_object(
            self.bucket,
            key,
            data,
            length=len(content),
            content_type=content_type,
        )

    def read(self, key: str) -> Optional[bytes]:
        try:
            resp = self.client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()
        except self._S3Error as e:
            if getattr(e, "code", "") == "NoSuchKey":
                return None
            raise

    def delete(self, key: str) -> None:
        try:
            self.client.remove_object(self.bucket, key)
        except self._S3Error as e:
            if getattr(e, "code", "") != "NoSuchKey":
                raise

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except self._S3Error:
            return False

    @property
    def name(self) -> str:
        return f"minio({self.bucket}@{self.client._base_url._url.netloc})"


# ─── Factory ───────────────────────────────────────────────────────────────


_singleton = None


def get_storage(upload_dir: str = "uploads"):
    """Return the active storage backend (constructed once per process)."""
    global _singleton
    if _singleton is not None:
        return _singleton

    endpoint = os.environ.get("MINIO_ENDPOINT", "").strip()
    if endpoint:
        try:
            access_key = os.environ.get("MINIO_ACCESS_KEY", "").strip()
            secret_key = os.environ.get("MINIO_SECRET_KEY", "").strip()
            bucket = os.environ.get("MINIO_BUCKET", "rfs-uploads").strip()
            secure = os.environ.get("MINIO_USE_SSL", "false").lower() in ("1", "true", "yes")
            if not access_key or not secret_key:
                raise RuntimeError("MINIO_ACCESS_KEY / MINIO_SECRET_KEY required")
            _singleton = MinIOStorage(endpoint, access_key, secret_key, bucket, secure=secure)
            logger.info(f"Storage backend: {_singleton.name}")
            return _singleton
        except Exception as e:
            logger.warning(f"MinIO init failed ({e}); falling back to LocalStorage")

    _singleton = LocalStorage(upload_dir)
    logger.info(f"Storage backend: {_singleton.name}")
    return _singleton


def reset_storage() -> None:
    """Test hook — clears the singleton so a new backend can be installed."""
    global _singleton
    _singleton = None
