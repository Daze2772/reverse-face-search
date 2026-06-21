"""Maigret integration — cross-platform username presence detection."""

import asyncio
import logging
import json
import subprocess
from typing import List, Dict, Any, Optional

logger = logging.getLogger("correlate.maigret")


class MaigretRunner:
    """Run Maigret to correlate usernames across 300+ platforms."""

    def __init__(self, config):
        self.config = config
        self.maigret_path = config.maigret.path

    async def run(self, usernames: List[Dict[str, str]]) -> Dict[str, Any]:
        """Run Maigret for each username and aggregate results."""
        results = {}

        # Run sequentially to respect rate limits
        for user_entry in usernames:
            username = user_entry["username"]
            try:
                logger.info(f"[maigret] Searching username: {username}")
                result = await self._search_username(username)
                results[username] = result
            except Exception as e:
                logger.error(f"[maigret] Error searching {username}: {e}")
                results[username] = {"error": str(e), "sites": [], "username": username}

        return results

    async def _search_username(self, username: str) -> Dict[str, Any]:
        """Run Maigret for a single username and parse results."""
        cmd = self._build_command(username)

        try:
            # Run maigret as subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.maigret.timeout_per_username,
            )

            if process.returncode != 0 and process.returncode is not None:
                err_text = stderr.decode("utf-8", errors="replace")
                logger.warning(f"[maigret] Process returned {process.returncode}: {err_text[:500]}")

            output = stdout.decode("utf-8", errors="replace")

            # Parse Maigret's JSON output (if --json flag used)
            sites = self._parse_output(output, username)

            # If maigret wrote a JSON report, try to read it
            report_path = self._find_report(username)
            if report_path:
                report_sites = self._parse_report(report_path)
                if report_sites:
                    sites = self._merge_sites(sites, report_sites)

            logger.info(f"[maigret] {username}: {len(sites)} platforms found")

            return {
                "username": username,
                "sites": sites,
                "total_sites_checked": len(sites),
                "hits": [s for s in sites if s.get("found", False)],
                "hit_count": sum(1 for s in sites if s.get("found", False)),
            }

        except asyncio.TimeoutError:
            logger.warning(f"[maigret] Timeout for username: {username}")
            return {"username": username, "sites": [], "error": "timeout", "hit_count": 0}
        except Exception as e:
            logger.error(f"[maigret] Exception for {username}: {e}")
            return {"username": username, "sites": [], "error": str(e), "hit_count": 0}

    def _build_command(self, username: str) -> List[str]:
        """Build the Maigret CLI command."""
        cmd = [
            self.maigret_path,
            username,
            "--no-recursion",
            "--no-color",
            "--no-progressbar",
            "--timeout", "15",
            "--top-sites", str(self.config.maigret.max_sites),
        ]
        return cmd

    def _parse_output(self, output: str, username: str) -> List[Dict]:
        """Parse Maigret's text/JSON output into structured site results."""
        sites = []

        # Try to find JSON block in output
        try:
            # Maigret may output JSON on a single line or multiple
            json_start = output.find("{")
            json_end = output.rfind("}")
            if json_start >= 0 and json_end > json_start:
                json_str = output[json_start:json_end + 1]
                data = json.loads(json_str)
                if isinstance(data, dict):
                    for site_name, site_data in data.items():
                        if isinstance(site_data, dict):
                            sites.append({
                                "site": site_name,
                                "url": site_data.get("url_user", ""),
                                "found": site_data.get("status", {}).get("exists", False) if isinstance(site_data.get("status"), dict) else False,
                                "response_time": site_data.get("status", {}).get("http_status", 0),
                            })
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        # Fallback: parse text output line by line
        if not sites:
            for line in output.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Maigret format: [+] or [-] followed by site info
                if line.startswith("[+]"):
                    parts = line[3:].strip().split(":", 1)
                    site_name = parts[0].strip() if parts else "unknown"
                    url = parts[1].strip() if len(parts) > 1 else ""
                    sites.append({
                        "site": site_name,
                        "url": url,
                        "found": True,
                    })
                elif line.startswith("[-]"):
                    parts = line[3:].strip().split(":", 1)
                    site_name = parts[0].strip() if parts else "unknown"
                    sites.append({
                        "site": site_name,
                        "url": "",
                        "found": False,
                    })

        return sites

    def _find_report(self, username: str) -> Optional[str]:
        """Find Maigret's generated JSON report file."""
        import glob
        patterns = [
            f"reports/report_{username}_*.json",
            f"report_{username}_*.json",
            f"reports/{username}.json",
            "reports/*.json",
        ]
        for pattern in patterns:
            matches = sorted(glob.glob(pattern), key=lambda x: __import__("os").path.getmtime(x), reverse=True)
            if matches:
                return matches[0]
        return None

    def _parse_report(self, report_path: str) -> List[Dict]:
        """Parse a Maigret JSON report file."""
        try:
            with open(report_path, "r") as f:
                data = json.load(f)

            sites = []
            if isinstance(data, dict):
                for site_name, site_data in data.items():
                    if isinstance(site_data, dict):
                        status = site_data.get("status", {})
                        sites.append({
                            "site": site_name,
                            "url": site_data.get("url_user", site_data.get("url", "")),
                            "found": status.get("exists", False) if isinstance(status, dict) else False,
                            "response_time": status.get("http_status", 0) if isinstance(status, dict) else 0,
                        })
            return sites
        except Exception as e:
            logger.error(f"[maigret] Report parse error: {e}")
            return []

    def _merge_sites(self, existing: List[Dict], new: List[Dict]) -> List[Dict]:
        """Merge two site lists, preferring 'found' status."""
        merged = {s["site"]: s for s in existing}
        for s in new:
            site_name = s["site"]
            if site_name in merged:
                if s.get("found") and not merged[site_name].get("found"):
                    merged[site_name] = s
            else:
                merged[site_name] = s
        return list(merged.values())
