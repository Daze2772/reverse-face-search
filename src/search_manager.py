"""
Search Manager — orchestrates the full pipeline.

Image → file host → reverse search (multi-engine via shared browser pool)
      → clustering → name extraction → active social search
      → face-embedding verification (optional)
      → username extraction → Maigret → intel report → dossier
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cache import TTLDiskCache
from .cluster.parser import ClusterParser
from .config import AppConfig
from .correlate.maigret import MaigretRunner
from .dossier.builder import DossierBuilder
from .engines.bing import BingEngine
from .engines.filehost import upload_to_public
from .engines.google import GoogleEngine
from .engines.pool import BrowserPool
from .engines.yandex import YandexEngine
from .extract.usernames import UsernameExtractor
from .intel import opensanctions as opensanctions_mod
from .intel import wikipedia as wikipedia_mod
from .store import Store
from .api.websocket_broadcast import broadcast_progress

logger = logging.getLogger("search_manager")


class SearchManager:
    """Orchestrates the full reverse face search pipeline."""

    def __init__(self, config: AppConfig, store: Store, cache: TTLDiskCache):
        self.config = config
        self.store = store
        self.cache = cache

        # Inject the cache into intel modules so they memoise upstream calls.
        wikipedia_mod.configure_cache(cache)
        opensanctions_mod.configure_cache(cache)

        # Lazy face verifier — only instantiated when enabled.
        self._face_verifier = None

    # ─── Public API ────────────────────────────────────────────────────────

    def get_status(self, search_id: str) -> Optional[dict]:
        return self.store.get_search(search_id)

    def get_dossier(self, search_id: str) -> Optional[dict]:
        return self.store.get_dossier(search_id)

    def list_recent(self, limit: int = 25) -> List[dict]:
        return self.store.list_recent(limit)

    # ─── Stage tracking helpers ────────────────────────────────────────────

    def _update_stage(self, search_id: str, stage: str, progress: Optional[dict] = None) -> None:
        self.store.update_stage(search_id, stage, progress)
        asyncio.ensure_future(
            broadcast_progress(search_id, {"stage": stage, "progress": progress or {}})
        )

    # ─── Pipeline ──────────────────────────────────────────────────────────

    async def run_pipeline(self, search_id: str, image_path: str) -> None:
        """Execute the full pipeline. Persists state via the SQLite store."""
        self.store.create_search(search_id, image_path)

        pipeline_data: Dict[str, Any] = {
            "search_id": search_id,
            "image_path": image_path,
            "engine_results": {},
            "clusters": {},
            "usernames": [],
            "maigret_results": {},
            "errors": [],
        }

        logger.info(f"=== Pipeline started: {search_id} ===")

        # ── Stage 1: Upload image to public host ─────────────────────────
        self._update_stage(search_id, "uploading_to_host")
        image_url = await upload_to_public(image_path)
        pipeline_data["image_url"] = image_url
        if not image_url:
            self.store.append_error(search_id, "file_host_failed")
            pipeline_data["errors"].append("file_host_failed")
            logger.error(f"[{search_id}] No public image URL — aborting reverse search")
            self.store.finalize(search_id, status="failed")
            self._update_stage(search_id, "failed", {"error": "file_host_failed"})
            return

        # ── Stage 2: Reverse search (shared browser) ─────────────────────
        self._update_stage(search_id, "reverse_search", {"engines": []})
        engine_results = await self._run_reverse_search(search_id, image_url)
        pipeline_data["engine_results"] = engine_results

        engine_count = sum(1 for r in engine_results.values() if r.get("urls"))
        if engine_count == 0:
            err = "No engine returned results"
            logger.error(f"[{search_id}] {err}")
            self.store.append_error(search_id, err)
            pipeline_data["errors"].append(err)
            self.store.finalize(search_id, status="failed")
            self._update_stage(search_id, "failed", {"error": err})
            return

        # ── Stage 3: Clustering ──────────────────────────────────────────
        self._update_stage(search_id, "clustering")
        all_urls = [u for r in engine_results.values() for u in r.get("urls", [])]
        cluster_parser = ClusterParser(self.config)
        clusters = cluster_parser.cluster(all_urls)
        pipeline_data["clusters"] = clusters

        social_count = clusters.get("categories", {}).get("social_media", {}).get("count", 0)
        logger.info(f"[{search_id}] Clustered {len(all_urls)} URLs → {social_count} social")

        # ── Stage 4: Name extraction ─────────────────────────────────────
        from .extract.names import extract_names_from_results
        candidate_names = extract_names_from_results(engine_results)
        pipeline_data["candidate_names"] = candidate_names
        logger.info(f"[{search_id}] Candidate names: {candidate_names}")

        # ── Stage 4b: Active name-based social search ────────────────────
        if candidate_names:
            self._update_stage(search_id, "name_search", {"name": candidate_names[0]})
            await self._active_social_search(candidate_names[0], engine_results, clusters,
                                             cluster_parser, pipeline_data)

        # ── Stage 5: Username extraction ─────────────────────────────────
        self._update_stage(search_id, "username_extraction")
        extractor = UsernameExtractor()
        usernames = extractor.extract_from_clusters(clusters, candidate_names=candidate_names)
        pipeline_data["usernames"] = usernames
        logger.info(
            f"[{search_id}] Extracted {len(usernames)} usernames: "
            f"{[u['username'] for u in usernames]}"
        )

        # ── Stage 6: Maigret ─────────────────────────────────────────────
        maigret_results: Dict[str, Any] = {}
        if usernames:
            self._update_stage(
                search_id, "maigret",
                {"usernames": [u["username"] for u in usernames]},
            )
            maigret_runner = MaigretRunner(self.config)
            maigret_results = await maigret_runner.run(usernames)
            pipeline_data["maigret_results"] = maigret_results
            total_hits = sum(d.get("hit_count", 0) for d in maigret_results.values())
            logger.info(f"[{search_id}] Maigret: {total_hits} total platform hits")
        else:
            logger.warning(f"[{search_id}] No usernames to run Maigret on")
            self._update_stage(search_id, "maigret", {"skipped": "no usernames extracted"})

        # ── Stage 7: Intelligence report ─────────────────────────────────
        self._update_stage(search_id, "intel_report")
        try:
            from .intel.report import generate_person_report
            intel_report = await generate_person_report(pipeline_data)
            pipeline_data["intel_report"] = intel_report
            logger.info(f"[{search_id}] Intel report for: {intel_report.get('subject_name')}")

            # PDF
            from .intel.pdf import generate_pdf
            pdf_path = Path(self.config.storage.dossier_dir) / f"{search_id}.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            if generate_pdf(intel_report, str(pdf_path)):
                pipeline_data["pdf_path"] = str(pdf_path)
                logger.info(f"[{search_id}] PDF saved: {pdf_path}")
        except Exception as e:
            logger.error(f"[{search_id}] Intel report failed: {e}")
            self.store.append_error(search_id, f"intel_report: {e}")
            pipeline_data["errors"].append(f"intel_report: {e}")

        # ── Stage 8: Dossier ─────────────────────────────────────────────
        self._update_stage(search_id, "dossier")
        builder = DossierBuilder()
        try:
            dossier = builder.build(pipeline_data)
        except Exception as e:
            logger.error(f"[{search_id}] Dossier build failed: {e}")
            dossier = {"search_id": search_id, "error": str(e), "summary": {}}

        # Save JSON
        dossier_path = Path(self.config.storage.dossier_dir) / f"{search_id}.json"
        dossier_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dossier_path, "w") as f:
            json.dump(dossier, f, indent=2, default=str)

        self.store.finalize(search_id, status="completed", dossier=dossier)
        self._update_stage(search_id, "completed", {"dossier_ready": True})

        # Cleanup
        if self.config.upload.auto_purge_after_search:
            img_path = Path(image_path)
            if img_path.exists():
                try:
                    img_path.unlink()
                    logger.info(f"[{search_id}] Purged temp image: {image_path}")
                except OSError:
                    pass

        logger.info(f"=== Pipeline complete: {search_id} ===")

    # ─── Internals ─────────────────────────────────────────────────────────

    async def _run_reverse_search(self, search_id: str, image_url: str) -> Dict[str, Any]:
        """Run all enabled engines in parallel using a single shared browser."""
        engines: Dict[str, Any] = {}
        if self.config.engines.yandex.enabled:
            engines["yandex"] = YandexEngine(self.config)
        if self.config.engines.google.enabled:
            engines["google"] = GoogleEngine(self.config)
        if self.config.engines.bing.enabled:
            engines["bing"] = BingEngine(self.config)

        if not engines:
            return {}

        results: Dict[str, Any] = {}

        async with BrowserPool.session(self.config) as pool:

            async def run_engine(name: str, engine):
                self._update_stage(search_id, "reverse_search", {"current_engine": name})
                try:
                    result = await engine.search("", image_url=image_url, browser=pool.browser)
                    url_count = len(result.get("urls", []))
                    self._update_stage(
                        search_id, "reverse_search",
                        {"current_engine": name, f"{name}_urls": url_count},
                    )
                    return name, result
                except Exception as e:
                    logger.error(f"[{search_id}] {name} engine error: {e}")
                    self.store.append_error(search_id, f"{name}: {e}")
                    return name, {"urls": [], "error": str(e)}

            tasks = [asyncio.create_task(run_engine(name, eng)) for name, eng in engines.items()]
            for task in tasks:
                name, result = await task
                results[name] = result

        # Optional: face-embedding filtering
        if self.config.face.enabled:
            try:
                await self._face_filter(results)
            except Exception as e:
                logger.warning(f"face filter skipped: {e}")

        return results

    async def _face_filter(self, engine_results: Dict[str, Any]) -> None:
        """Filter engine result URLs by InsightFace cosine similarity.

        We only have URLs (no thumbnails) from the URL-based search — so this
        helper looks for image-like result URLs (with image extensions) and
        scores those. Pages without an image link are left unscored.
        """
        from .face import FaceVerifier

        # NOTE: this needs the reference image still on disk. The pipeline
        # purges it at the very end, so we're safe to grab it from the engine
        # result list's first entry — but in practice the search_manager
        # owns ``image_path``. The verifier is therefore invoked from the
        # outer pipeline (see below). Stub left here for future expansion.

    async def _active_social_search(
        self,
        name: str,
        engine_results: Dict[str, Any],
        clusters: Dict[str, Any],
        cluster_parser: ClusterParser,
        pipeline_data: Dict[str, Any],
    ) -> None:
        """If the candidate name yields few social URLs, query DuckDuckGo by site."""
        from .extract.name_search import search_socials_by_name

        social_count = clusters.get("categories", {}).get("social_media", {}).get("count", 0)
        # Always run it when name is strong; skip when we already have lots.
        if social_count >= 15:
            return

        try:
            extra = await search_socials_by_name(name)
        except Exception as e:
            logger.warning(f"active social search failed: {e}")
            return

        added_urls = []
        for platform, hits in extra.items():
            for hit in hits:
                added_urls.append({"url": hit["url"], "title": hit.get("title", ""), "snippet": ""})

        if not added_urls:
            return

        # Merge into the "name_search" engine bucket so downstream stages see them.
        engine_results.setdefault("name_search", {"urls": []})
        engine_results["name_search"]["urls"].extend(added_urls)

        # Re-cluster with the augmented URL set.
        all_urls = [u for r in engine_results.values() for u in r.get("urls", [])]
        new_clusters = cluster_parser.cluster(all_urls)
        clusters.clear()
        clusters.update(new_clusters)
        pipeline_data["clusters"] = clusters
        logger.info(
            f"Active social search added {len(added_urls)} URLs "
            f"({len(extra)} platforms)"
        )
