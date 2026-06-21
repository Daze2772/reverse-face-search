"""Maigret integration — cross-platform username presence detection.

Pipes Maigret's JSON output via ``--json simple`` so we don't have to scrape
its CLI text format. The legacy text-fallback parser is kept for robustness.
"""

import asyncio
import glob
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("correlate.maigret")


class MaigretRunner:
    """Run Maigret to correlate usernames across 300+ platforms."""

    def __init__(self, config):
        self.config = config
        self.maigret_path = config.maigret.path

    async def run(self, usernames: List[Dict[str, str]]) -> Dict[str, Any]:
        """Run Maigret for each username and aggregate results."""
        results: Dict[str, Any] = {}
        # Run sequentially — Maigret already hits many sites in parallel per
        # username, and stacking N more would get us rate-limited everywhere.
        for entry in usernames:
            username = entry["username"]
            try:
                logger.info(f"[maigret] Searching username: {username}")
                results[username] = await self._search_username(username)
            except Exception as e:
                logger.error(f"[maigret] Error searching {username}: {e}")
                results[username] = {"error": str(e), "sites": [], "username": username}
        return results

    async def _search_username(self, username: str) -> Dict[str, Any]:
        """Run Maigret for a single username and parse results."""
        # Use a per-username scratch dir so concurrent runs don't trample.
        report_dir = Path("reports") / username
        report_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._build_command(username, report_dir)
        logger.debug(f"[maigret] cmd: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.maigret.timeout_per_username,
            )

            if process.returncode not in (0, None):
                err_text = stderr.decode("utf-8", errors="replace")
                logger.warning(f"[maigret] exit={process.returncode}: {err_text[:300]}")

            sites = self._parse_report_files(report_dir)
            if not sites:
                # Fall back to scraping the text output.
                sites = self._parse_text_output(stdout.decode("utf-8", errors="replace"))

            hits = [s for s in sites if s.get("found")]
            logger.info(f"[maigret] {username}: {len(hits)} hits / {len(sites)} sites")

            return {
                "username": username,
                "sites": sites,
                "total_sites_checked": len(sites),
                "hits": hits,
                "hit_count": len(hits),
            }

        except asyncio.TimeoutError:
            logger.warning(f"[maigret] timeout for username: {username}")
            return {"username": username, "sites": [], "error": "timeout", "hit_count": 0}
        except FileNotFoundError:
            logger.error(f"[maigret] binary not found at: {self.maigret_path}")
            return {
                "username": username, "sites": [],
                "error": "maigret binary missing — pip install maigret",
                "hit_count": 0,
            }
        except Exception as e:
            logger.error(f"[maigret] exception for {username}: {e}")
            return {"username": username, "sites": [], "error": str(e), "hit_count": 0}

    def _build_command(self, username: str, report_dir: Path) -> List[str]:
        """Build the Maigret CLI command. ``--json simple`` makes parsing trivial."""
        return [
            self.maigret_path,
            username,
            "--no-recursion",
            "--no-color",
            "--no-progressbar",
            "--timeout", "15",
            "--top-sites", str(self.config.maigret.max_sites),
            "--folderoutput", str(report_dir),
            "--json", "simple",
        ]

    def _parse_report_files(self, report_dir: Path) -> List[Dict[str, Any]]:
        """Look for the JSON report Maigret writes into the folder."""
        candidates = sorted(
            report_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.debug(f"[maigret] could not parse {path}: {e}")
                continue

            if not isinstance(data, dict):
                continue

            sites: List[Dict[str, Any]] = []
            for site_name, site_data in data.items():
                if not isinstance(site_data, dict):
                    continue
                status = site_data.get("status") if isinstance(site_data.get("status"), dict) else {}
                sites.append({
                    "site": site_name,
                    "url": site_data.get("url_user", site_data.get("url", "")),
                    "found": status.get("exists", False) if status else False,
                    "response_time": status.get("http_status", 0) if status else 0,
                })
            if sites:
                return sites
        return []

    @staticmethod
    def _parse_text_output(output: str) -> List[Dict[str, Any]]:
        """Fallback: parse Maigret's text output line by line."""
        sites: List[Dict[str, Any]] = []
        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("[+]"):
                parts = line[3:].strip().split(":", 1)
                sites.append({
                    "site": parts[0].strip() if parts else "unknown",
                    "url": parts[1].strip() if len(parts) > 1 else "",
                    "found": True,
                })
            elif line.startswith("[-]"):
                parts = line[3:].strip().split(":", 1)
                sites.append({
                    "site": parts[0].strip() if parts else "unknown",
                    "url": "",
                    "found": False,
                })
        return sites
