"""OpenSanctions risk evaluation — PEP, sanctions, criminal exposure check."""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("intel.opensanctions")

OPEN_SANCTIONS_API = "https://api.opensanctions.org/search/default"


async def check_person(name: str) -> Optional[Dict[str, Any]]:
    """Check a person against OpenSanctions PEP/sanctions database.
    
    Returns None if not found, or a dict with risk details.
    """
    import httpx

    try:
        params = {
            "q": name,
            "limit": 3,
        }
        async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": "ReverseFaceSearch/2.0"
        }) as client:
            resp = await client.get(OPEN_SANCTIONS_API, params=params)
            
            if resp.status_code == 401:
                logger.info("OpenSanctions requires authentication — skipping risk check")
                return None
            if resp.status_code != 200:
                logger.warning(f"OpenSanctions returned {resp.status_code}")
                return None
            data = resp.json()
            
            results = data.get("results", [])
            if not results:
                logger.info(f"OpenSanctions: no matches for '{name}'")
                return None
            
            # Find best match
            best = results[0]
            score = best.get("score", 0)
            
            if score < 0.7:  # Low confidence match
                logger.info(f"OpenSanctions: low confidence match ({score:.2f}) for '{name}'")
                return None
            
            # Extract risk data
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
            
            logger.info(f"OpenSanctions: match for '{name}' — risk={risk_data['risk_level']}")
            return risk_data

    except Exception as e:
        logger.warning(f"OpenSanctions check failed for '{name}': {e}")
        return None


def _assess_risk(result: Dict) -> str:
    """Assess risk level from OpenSanctions result."""
    topics = [t.lower() for t in result.get("topics", [])]
    datasets = [d.lower() for d in result.get("datasets", [])]
    schema = result.get("schema", "").lower()
    
    # High risk indicators
    high_risk = {"sanctions", "crime", "terrorism", "wanted", "fugitive", "corruption", "trafficking"}
    medium_risk = {"pep", "politician", "diplomat", "government", "official"}
    
    all_text = " ".join(topics + datasets + [schema])
    
    for indicator in high_risk:
        if indicator in all_text:
            return "HIGH"
    
    for indicator in medium_risk:
        if indicator in all_text:
            return "MEDIUM"
    
    return "LOW"


def format_risk_summary(risk_data: Optional[Dict]) -> str:
    """Format risk data into human-readable summary."""
    if not risk_data or not risk_data.get("found"):
        return "No sanctions/PEP exposure found in OpenSanctions database."
    
    level = risk_data.get("risk_level", "UNKNOWN")
    lines = [
        f"**Risk Level: {level}**",
        f"Match: {risk_data.get('name', 'Unknown')} ({risk_data.get('match_score', 0):.0%} confidence)",
        f"Categories: {', '.join(risk_data.get('topics', [])) or 'N/A'}",
    ]
    
    if risk_data.get("countries"):
        lines.append(f"Countries: {', '.join(risk_data['countries'])}")
    
    if risk_data.get("summary"):
        lines.append(f"\n{risk_data['summary'][:500]}")
    
    return "\n".join(lines)
