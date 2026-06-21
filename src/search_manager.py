"""
Search Manager — orchestrates the full pipeline.
Image → Reverse Search (multi-engine) → Clustering → Username Extraction → Maigret → Dossier
"""

import asyncio
import logging
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

from .config import AppConfig
from .engines.yandex import YandexEngine
from .engines.google import GoogleEngine
from .engines.bing import BingEngine
from .cluster.parser import ClusterParser
from .extract.usernames import UsernameExtractor
from .correlate.maigret import MaigretRunner
from .dossier.builder import DossierBuilder
from .engines.filehost import upload_to_public
from .api.websocket_broadcast import broadcast_progress

logger = logging.getLogger("search_manager")


class SearchManager:
    """Orchestrates the full reverse face search pipeline."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.active_searches: Dict[str, dict] = {}
        self.dossiers: Dict[str, dict] = {}

    def _init_status(self, search_id: str) -> dict:
        """Initialize status tracking for a new search."""
        status = {
            "search_id": search_id,
            "stage": "uploaded",
            "progress": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "errors": [],
        }
        self.active_searches[search_id] = status
        return status

    def _update_stage(self, search_id: str, stage: str, progress_data: Optional[dict] = None):
        """Update the current stage and optional progress details."""
        if search_id in self.active_searches:
            self.active_searches[search_id]["stage"] = stage
            if progress_data:
                self.active_searches[search_id]["progress"].update(progress_data)
            asyncio.ensure_future(
                broadcast_progress(search_id, {"stage": stage, "progress": progress_data or {}})
            )

    def get_status(self, search_id: str) -> Optional[dict]:
        """Get current status of a search."""
        return self.active_searches.get(search_id)

    def get_dossier(self, search_id: str) -> Optional[dict]:
        """Get completed dossier."""
        return self.dossiers.get(search_id)

    async def run_pipeline(self, search_id: str, image_path: str):
        """Execute the full pipeline stages in order."""
        self._init_status(search_id)
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

        # ── Upload image to public host for URL-based reverse search ──
        self._update_stage(search_id, "uploading_to_host")
        image_url = await upload_to_public(image_path)
        if image_url:
            pipeline_data["image_url"] = image_url
            logger.info(f"[{search_id}] Public URL: {image_url}")
        else:
            logger.warning(f"[{search_id}] Could not upload to public host — engines will use fallback")
            pipeline_data["errors"].append("file_host_failed")

        # ── Stage 2: Multi-engine reverse search ──
        self._update_stage(search_id, "reverse_search", {"engines": []})
        engine_results = await self._run_reverse_search(image_path, search_id, image_url)
        pipeline_data["engine_results"] = engine_results

        engine_count = sum(1 for r in engine_results.values() if r.get("urls"))
        if engine_count == 0:
            err = "No engine returned results"
            logger.error(f"[{search_id}] {err}")
            pipeline_data["errors"].append(err)
            self._update_stage(search_id, "failed", {"error": err})
            self.active_searches[search_id]["errors"].append(err)
            return

        # ── Stage 3: Result clustering ──
        self._update_stage(search_id, "clustering")
        all_urls = []
        for engine_name, result in engine_results.items():
            for url_entry in result.get("urls", []):
                all_urls.append(url_entry)

        cluster_parser = ClusterParser(self.config)
        clusters = cluster_parser.cluster(all_urls)
        pipeline_data["clusters"] = clusters

        social_count = sum(len(v) for k, v in clusters.items() if k == "social_media")
        logger.info(f"[{search_id}] Clustered {len(all_urls)} URLs → {social_count} social")

        # ── Name extraction from search results ──
        from .extract.names import extract_names_from_results
        candidate_names = extract_names_from_results(engine_results)
        pipeline_data["candidate_names"] = candidate_names
        logger.info(f"[{search_id}] Candidate names: {candidate_names}")

        # ── Stage 4: Username extraction ──
        self._update_stage(search_id, "username_extraction")
        extractor = UsernameExtractor()
        usernames = extractor.extract_from_clusters(clusters, candidate_names=candidate_names)
        pipeline_data["usernames"] = usernames
        logger.info(f"[{search_id}] Extracted {len(usernames)} usernames: {[u['username'] for u in usernames]}")

        # ── Stage 5: Maigret cross-platform correlation ──
        maigret_results = {}
        if usernames:
            self._update_stage(search_id, "maigret", {"usernames": [u["username"] for u in usernames]})
            maigret_runner = MaigretRunner(self.config)
            maigret_results = await maigret_runner.run(usernames)
            pipeline_data["maigret_results"] = maigret_results

            total_hits = sum(
                len(sites) for user_data in maigret_results.values()
                for sites in [user_data.get("sites", [])]
            )
            logger.info(f"[{search_id}] Maigret: {total_hits} total platform hits")
        else:
            logger.warning(f"[{search_id}] No usernames to run Maigret on")
            self._update_stage(search_id, "maigret", {"skipped": "no usernames extracted"})

        # ── V2: Intelligence Report Generation ──
        self._update_stage(search_id, "intel_report")
        from .intel.report import generate_person_report
        try:
            intel_report = await generate_person_report(pipeline_data)
            pipeline_data["intel_report"] = intel_report
            logger.info(f"[{search_id}] Intel report generated for: {intel_report.get('subject_name')}")
            
            # Generate PDF
            from .intel.pdf import generate_pdf
            pdf_path = Path("dossiers") / f"{search_id}.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_bytes = generate_pdf(intel_report, str(pdf_path))
            if pdf_bytes:
                pipeline_data["pdf_path"] = str(pdf_path)
                logger.info(f"[{search_id}] PDF saved: {pdf_path}")
        except Exception as e:
            logger.error(f"[{search_id}] Intel report generation failed: {e}")
            pipeline_data["errors"].append(f"intel_report: {str(e)}")

        # ── Stage 6: Dossier aggregation ──
        self._update_stage(search_id, "dossier")
        builder = DossierBuilder()
        try:
            dossier = builder.build(pipeline_data)
        except Exception as e:
            logger.error(f"[{search_id}] Dossier build failed: {e}")
            dossier = {"search_id": search_id, "error": str(e), "summary": {}}
        self.dossiers[search_id] = dossier

        # Save dossier JSON to disk
        dossier_path = Path("dossiers") / f"{search_id}.json"
        dossier_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dossier_path, "w") as f:
            json.dump(dossier, f, indent=2, default=str)

        logger.info(f"[{search_id}] Dossier saved to {dossier_path}")

        # ── Done ──
        self._update_stage(search_id, "completed", {"dossier_ready": True})
        self.active_searches[search_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        # Auto-purge temp image
        if self.config.upload.auto_purge_after_search:
            img_path = Path(image_path)
            if img_path.exists():
                img_path.unlink()
                logger.info(f"[{search_id}] Purged temp image: {image_path}")

        logger.info(f"=== Pipeline complete: {search_id} ===")

    async def _run_reverse_search(self, image_path: str, search_id: str, image_url: Optional[str] = None) -> Dict[str, Any]:
        """Run all enabled engines in parallel."""
        tasks = {}
        engines = {}

        if self.config.engines.yandex.enabled:
            engines["yandex"] = YandexEngine(self.config)
        if self.config.engines.google.enabled:
            engines["google"] = GoogleEngine(self.config)
        if self.config.engines.bing.enabled:
            engines["bing"] = BingEngine(self.config)

        async def run_engine(name: str, engine):
            self._update_stage(search_id, "reverse_search", {"current_engine": name})
            try:
                result = await engine.search(image_path, image_url=image_url)
                url_count = len(result.get("urls", []))
                logger.info(f"[{search_id}] {name}: {url_count} URLs")
                self._update_stage(search_id, "reverse_search", {
                    "current_engine": name,
                    f"{name}_urls": url_count
                })
                return name, result
            except Exception as e:
                logger.error(f"[{search_id}] {name} engine error: {e}")
                self.active_searches[search_id]["errors"].append(f"{name}: {str(e)}")
                return name, {"urls": [], "error": str(e)}

        for name, engine in engines.items():
            tasks[name] = asyncio.create_task(run_engine(name, engine))

        results = {}
        for name, task in tasks.items():
            try:
                eng_name, result = await task
                results[eng_name] = result
            except Exception as e:
                logger.error(f"[{search_id}] Task {name} failed: {e}")
                results[name] = {"urls": [], "error": str(e)}

        return results
