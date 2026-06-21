"""Dossier aggregation — assemble all pipeline data into structured output."""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger("dossier")


class DossierBuilder:
    """Build the final dossier from pipeline data."""

    def build(self, pipeline_data: Dict[str, Any]) -> Dict[str, Any]:
        """Assemble a full dossier from all pipeline stages."""
        search_id = pipeline_data.get("search_id", "unknown")
        now = datetime.now(timezone.utc).isoformat()

        # ── Engine Results Summary ──
        engine_summary = {}
        total_engine_urls = 0
        for engine_name, result in pipeline_data.get("engine_results", {}).items():
            urls = result.get("urls", [])
            engine_summary[engine_name] = {
                "url_count": len(urls),
                "error": result.get("error"),
                "sample_urls": [u.get("url", "") for u in urls[:5]],
            }
            total_engine_urls += len(urls)

        # ── Clustering Summary ──
        clusters = pipeline_data.get("clusters", {})
        cluster_summary = {}
        categories = clusters.get("categories", {})
        for cat, data in categories.items():
            if data.get("count", 0) > 0:
                cluster_summary[cat] = {
                    "url_count": data["count"],
                    "confidence": data.get("confidence", 0.0),
                }

        social_subs = clusters.get("social_sub_clusters", {})
        social_breakdown = {
            platform: len(urls)
            for platform, urls in social_subs.items()
        }

        # ── Username Summary ──
        usernames = pipeline_data.get("usernames", [])
        username_summary = [
            {
                "username": u["username"],
                "platforms": u["platforms"],
                "source_urls": u.get("urls", [])[:3],
            }
            for u in usernames
        ]

        # ── Maigret Summary ──
        maigret_data = pipeline_data.get("maigret_results", {})
        maigret_summary = {}
        total_maigret_hits = 0
        unique_platforms_with_hits = set()

        for username, data in maigret_data.items():
            sites = data.get("sites", [])
            hits = [s for s in sites if s.get("found", False)]
            for hit in hits:
                unique_platforms_with_hits.add(hit.get("site", ""))

            maigret_summary[username] = {
                "sites_checked": len(sites),
                "hits": len(hits),
                "hit_platforms": [h["site"] for h in hits],
                "error": data.get("error"),
            }
            total_maigret_hits += len(hits)

        # ── Full Dossier ──
        dossier = {
            "search_id": search_id,
            "generated_at": now,
            "summary": {
                "total_engine_urls": total_engine_urls,
                "total_clustered_urls": clusters.get("total_unique_urls", 0),
                "total_usernames_extracted": len(usernames),
                "total_maigret_platform_hits": total_maigret_hits,
                "unique_maigret_platforms": len(unique_platforms_with_hits),
                "subject_name": (pipeline_data.get("candidate_names") or [None])[0] or "Unknown",
            },
            "engines": engine_summary,
            "clusters": {
                "categories": cluster_summary,
                "social_media_breakdown": social_breakdown,
            },
            "usernames": username_summary,
            "cross_platform_correlation": maigret_summary,
            # V2: Intelligence report
            "intel_report": pipeline_data.get("intel_report"),
            "candidate_names": pipeline_data.get("candidate_names", []),
            "pdf_available": bool(pipeline_data.get("pdf_path")),
            # Full raw data sections
            "_raw": {
                "engine_results": pipeline_data.get("engine_results", {}),
                "clusters_full": clusters,
                "usernames_full": pipeline_data.get("usernames", []),
                "maigret_full": maigret_data,
            },
            "errors": pipeline_data.get("errors", []),
        }

        logger.info(f"Dossier built: {dossier['summary']}")
        return dossier
