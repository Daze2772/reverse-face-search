"""Face-embedding verification — filters reverse-image-search hits to the actual
person, not just visually similar shots.

This module is **opt-in** because InsightFace ships ~700 MB of ONNX models and
requires onnxruntime + opencv-python-headless. Enable via
``RFS_FACE_EMBEDDING_ENABLED=true`` in the environment.

API
---

* :class:`FaceVerifier` — load once, reuse across searches.
* :meth:`FaceVerifier.compare_against_reference` — given a reference image
  and a list of candidate image URLs, return a list of similarity scores.
"""

import asyncio
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger("face.embedding")


@dataclass
class FaceMatch:
    url: str
    similarity: float
    passed: bool


class FaceVerifier:
    """Wraps InsightFace's recognition pipeline behind a tiny façade."""

    def __init__(self, model_name: str = "buffalo_l", similarity_threshold: float = 0.55):
        self.model_name = model_name
        self.threshold = similarity_threshold
        self._app = None  # lazily instantiated

    # ─── Lifecycle ─────────────────────────────────────────────────────────

    def _ensure_loaded(self):
        if self._app is not None:
            return
        try:
            from insightface.app import FaceAnalysis
        except ImportError as e:
            raise RuntimeError(
                "insightface is not installed. Install with: pip install "
                "insightface onnxruntime opencv-python-headless numpy"
            ) from e
        logger.info(f"Loading InsightFace model={self.model_name} ...")
        app = FaceAnalysis(name=self.model_name, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        self._app = app
        logger.info("InsightFace ready")

    # ─── Embedding extraction ──────────────────────────────────────────────

    def _embed_from_path(self, image_path: str):
        import cv2
        import numpy as np
        self._ensure_loaded()

        img = cv2.imread(image_path)
        if img is None:
            return None
        faces = self._app.get(img)
        if not faces:
            return None
        # Pick the largest face — most likely the subject.
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        emb = faces[0].normed_embedding
        return np.asarray(emb, dtype="float32")

    def _embed_from_bytes(self, raw: bytes):
        import cv2
        import numpy as np
        self._ensure_loaded()

        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        faces = self._app.get(img)
        if not faces:
            return None
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        return np.asarray(faces[0].normed_embedding, dtype="float32")

    # ─── Public API ────────────────────────────────────────────────────────

    async def compare_against_reference(
        self,
        reference_image: str,
        candidate_image_urls: List[str],
        timeout: int = 10,
    ) -> List[FaceMatch]:
        """Return cosine-similarity scores for each candidate vs the reference.

        Candidates that cannot be downloaded / contain no face are skipped.
        The work is offloaded to a worker thread so we don't block the event
        loop on CV inference.
        """
        loop = asyncio.get_running_loop()
        ref = await loop.run_in_executor(None, self._embed_from_path, reference_image)
        if ref is None:
            logger.warning("Reference image has no detectable face")
            return []

        results: List[FaceMatch] = []

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            sem = asyncio.Semaphore(5)

            async def _one(url: str) -> Optional[FaceMatch]:
                async with sem:
                    try:
                        r = await client.get(url)
                        if r.status_code != 200 or not r.content:
                            return None
                        emb = await loop.run_in_executor(None, self._embed_from_bytes, r.content)
                        if emb is None:
                            return None
                        sim = float((ref * emb).sum())  # both L2-normalised → dot = cosine
                        return FaceMatch(url=url, similarity=sim, passed=sim >= self.threshold)
                    except Exception as e:
                        logger.debug(f"face compare failed for {url}: {e}")
                        return None

            tasks = [asyncio.create_task(_one(u)) for u in candidate_image_urls]
            for fut in asyncio.as_completed(tasks):
                match = await fut
                if match is not None:
                    results.append(match)

        return results
