"""OpenSanctions risk evaluation — PEP, sanctions, criminal exposure check.

The OpenSanctions search API requires authentication for all but a thin
free-tier slice. We read the key from ``OPENSANCTIONS_API_KEY`` (env), and
cache responses per name via :class:`~src.cache.TTLDiskCache`.
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("intel.opensanctions")

OPEN_SANCTIONS_API = "https://api.opensanctions.org/search/default"
USER_AGENT = "ReverseFaceSearch/2.0"

_cache = None


def configure_cache(cache) -> None:
    global _cache
    _cache = cache


async def check_person(name: str) -> Optional[Dict[str, Any]]:
    """Check a person against OpenSanctions PEP/sanctions database."""
    if not name or len(name) < 3:
        return None

    if _cache:
        cached = await _cache.get("opensanctions", name.lower())
        if cached is not None:
            logger.debug(f"OpenSanctions cache hit: {name}")
            return cached if cached.get("found") else None

    api_key = os.environ.get("OPENSANCTIONS_API_KEY", "").strip()
    headers = {"User-Agent": USER_AGENT}
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    try:
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            resp = await client.get(OPEN_SANCTIONS_API, params={"q": name, "limit": 3})
            if resp.status_code == 401:
                logger.info("OpenSanctions requires authentication — skipping")
                return None
            if resp.status_code != 200:
                logger.warning(f"OpenSanctions returned {resp.status_code}")
                return None

            data = resp.json()
            results = data.get("results", [])
            if not results:
                logger.info(f"OpenSanctions: no matches for '{name}'")
                if _cache:
                    await _cache.set("opensanctions", name.lower(), {"found": False})
                return None

            best = results[0]
            score = best.get("score", 0)
            if score < 0.7:
                logger.info(f"OpenSanctions: low confidence ({score:.2f}) for '{name}'")
                if _cache:
                    await _cache.set("opensanctions", name.lower(), {"found": False})
                return None

            risk_data = {
                "found": True,
                "name": best.get("caption", name),
                "match_score": round(score, 2),
                "countries": best.get("countries", []),
                "topics": best.get("topics", []),
                "datasets": best.get("datasets", []),
                "schema": best.get("schema", ""),
                "summary": best.get("excerpt", ""),
                "risk_level": _assess_risk(best),
            }
            logger.info(f"OpenSanctions: '{name}' → risk={risk_data['risk_level']}")
            if _cache:
                await _cache.set("opensanctions", name.lower(), risk_data)
            return risk_data

    except Exception as e:
        logger.warning(f"OpenSanctions check failed for '{name}': {e}")
        return None


def _assess_risk(result: Dict) -> str:
    topics = [t.lower() for t in result.get("topics", [])]
    datasets = [d.lower() for d in result.get("datasets", [])]
    schema = result.get("schema", "").lower()
    all_text = " ".join(topics + datasets + [schema])

    high_risk = {"sanctions", "crime", "terrorism", "wanted", "fugitive",
                 "corruption", "trafficking"}
    medium_risk = {"pep", "politician", "diplomat", "government", "official"}

    if any(ind in all_text for ind in high_risk):
        return "HIGH"
    if any(ind in all_text for ind in medium_risk):
        return "MEDIUM"
    return "LOW"


def format_risk_summary(risk_data: Optional[Dict]) -> str:
    if not risk_data or not risk_data.get("found"):
        return "No sanctions/PEP exposure found in OpenSanctions database."
    level = risk_data.get("risk_level", "UNKNOWN")
    lines = [
        f"**Risk Level: {level}**",
        f"Match: {risk_data.get('name', 'Unknown')} "
        f"({risk_data.get('match_score', 0):.0%} confidence)",
        f"Categories: {', '.join(risk_data.get('topics', [])) or 'N/A'}",
    ]
    if risk_data.get("countries"):
        lines.append(f"Countries: {', '.join(risk_data['countries'])}")
    if risk_data.get("summary"):
        lines.append(f"\n{risk_data['summary'][:500]}")
    return "\n".join(lines)
