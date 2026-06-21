"""Intelligence report generation — assemble complete person file from all intel sources."""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("intel.report")


async def generate_person_report(pipeline_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a complete intelligence report from all pipeline data.
    
    Combines: Wikipedia, OpenSanctions, affiliations, engine results, 
    username extraction, Maigret, and generates a narrative summary.
    """
    
    search_id = pipeline_data.get("search_id", "unknown")
    candidate_names = pipeline_data.get("candidate_names", [])
    primary_name = candidate_names[0] if candidate_names else "Unknown Person"
    
    report = {
        "report_id": search_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "subject_name": primary_name,
        "candidate_names": candidate_names,
    }
    
    # ── Wikipedia ──
    wiki_data = None
    if primary_name and primary_name != "Unknown Person":
        from .wikipedia import search_wikipedia
        wiki_data = await search_wikipedia(primary_name)
    report["wikipedia"] = wiki_data
    
    # ── OpenSanctions ──
    risk_data = None
    if primary_name and primary_name != "Unknown Person":
        from .opensanctions import check_person
        risk_data = await check_person(primary_name)
    report["risk_assessment"] = risk_data
    
    # ── Affiliations ──
    from .affiliations import extract_affiliations
    affiliations = extract_affiliations(pipeline_data.get("engine_results", {}))
    report["affiliations"] = affiliations
    
    # ── Search Summary ──
    engine_results = pipeline_data.get("engine_results", {})
    search_summary = {}
    total_urls = 0
    for eng_name, result in engine_results.items():
        count = len(result.get("urls", []))
        total_urls += count
        search_summary[eng_name] = {
            "url_count": count,
            "has_error": bool(result.get("error")),
        }
    report["search_summary"] = {
        "total_urls": total_urls,
        "engines": search_summary,
    }
    
    # ── Social Presence ──
    usernames = pipeline_data.get("usernames", [])
    social_presence = []
    for u in usernames:
        social_presence.append({
            "username": u.get("username"),
            "platforms": u.get("platforms", []),
            "name_match_score": u.get("name_match_score", 0),
            "quality_score": u.get("quality_score", 0),
        })
    report["social_presence"] = {
        "usernames_found": len(usernames),
        "accounts": social_presence,
    }
    
    # ── Maigret Summary ──
    maigret_data = pipeline_data.get("maigret_results", {})
    maigret_summary = {
        "usernames_searched": len(maigret_data),
        "total_platform_hits": sum(
            d.get("hit_count", 0) for d in maigret_data.values()
        ),
        "details": {
            uname: {
                "hits": d.get("hit_count", 0),
                "sites_checked": len(d.get("sites", [])),
            }
            for uname, d in maigret_data.items()
        }
    }
    report["cross_platform"] = maigret_summary
    
    # ── Public Figure Assessment ──
    report["public_figure"] = _assess_public_figure(wiki_data, engine_results, usernames)
    
    # ── Narrative Summary ──
    report["narrative"] = _generate_narrative(report)
    
    logger.info(f"Person report generated for: {primary_name}")
    return report


def _assess_public_figure(wiki_data, engine_results, usernames) -> Dict[str, Any]:
    """Determine if subject is a public figure and what level."""
    has_wiki = wiki_data and wiki_data.get("found")
    total_urls = sum(len(r.get("urls", [])) for r in (engine_results or {}).values())
    has_socials = len([u for u in usernames if u.get("name_match_score", 0) >= 0.5]) > 0
    
    if has_wiki:
        level = "PUBLIC_FIGURE"
        confidence = "HIGH"
    elif total_urls > 50:
        level = "LIKELY_PUBLIC"
        confidence = "MEDIUM"
    elif has_socials:
        level = "ONLINE_PRESENCE"
        confidence = "MEDIUM"
    elif total_urls > 10:
        level = "LOW_VISIBILITY"
        confidence = "LOW"
    else:
        level = "PRIVATE_INDIVIDUAL"
        confidence = "HIGH"
    
    return {
        "level": level,
        "confidence": confidence,
        "has_wikipedia": has_wiki,
        "total_search_results": total_urls,
        "matched_social_accounts": has_socials,
    }


def _generate_narrative(report: Dict[str, Any]) -> str:
    """Generate a narrative intelligence summary."""
    name = report.get("subject_name", "the subject")
    parts = [f"Intelligence Report: {name}", ""]
    
    # Wikipedia bio
    wiki = report.get("wikipedia", {}) or {}
    if wiki.get("found"):
        parts.append("## Identity")
        facts = wiki.get("facts", {})
        if facts.get("profession"):
            parts.append(f"{name} is identified as a {facts['profession']}.")
        if facts.get("nationality"):
            parts.append(f"Nationality: {facts['nationality']}.")
        if facts.get("birth_year"):
            parts.append(f"Born: {facts['birth_year']}.")
        if wiki.get("summary"):
            summary = wiki["summary"][:500]
            parts.append(f"\n{summary}")
        parts.append("")
    elif report.get("candidate_names"):
        names = report["candidate_names"]
        if names and names[0] != "Unknown Person":
            parts.append(f"## Identity\nName extracted from search results: {', '.join(names)}.")
            parts.append("No Wikipedia entry found — subject may not be a public figure.\n")
    
    # Risk
    risk = report.get("risk_assessment", {}) or {}
    if risk.get("found"):
        parts.append("## Risk Assessment")
        level = risk.get("risk_level", "UNKNOWN")
        parts.append(f"Risk Level: **{level}**")
        if risk.get("topics"):
            parts.append(f"Categories: {', '.join(risk['topics'])}")
        if risk.get("countries"):
            parts.append(f"Countries: {', '.join(risk['countries'])}")
        parts.append("")
    
    # Search footprint
    search = report.get("search_summary", {})
    total = search.get("total_urls", 0)
    parts.append(f"## Digital Footprint\n{total} URLs found across reverse image search engines.")
    for eng, data in search.get("engines", {}).items():
        parts.append(f"- {eng}: {data.get('url_count', 0)} results")
    parts.append("")
    
    # Social
    social = report.get("social_presence", {})
    accounts = social.get("accounts", [])
    if accounts:
        parts.append("## Social Media Presence")
        for acc in accounts:
            match = "✓" if acc.get("name_match_score", 0) >= 0.5 else "?"
            parts.append(f"- {match} {acc['username']} ({', '.join(acc.get('platforms', []))})")
        parts.append("")
    
    # Affiliations
    aff = report.get("affiliations", {})
    orgs = aff.get("organizations", [])
    locs = aff.get("locations", [])
    if orgs or locs:
        parts.append("## Context & Affiliations")
        if orgs:
            parts.append(f"Organizations: {', '.join(o['name'] for o in orgs[:5])}")
        if locs:
            parts.append(f"Locations: {', '.join(loc['name'] for loc in locs[:5])}")
        parts.append("")
    
    # Cross-platform
    cp = report.get("cross_platform", {})
    hits = cp.get("total_platform_hits", 0)
    if hits > 0:
        parts.append(f"## Cross-Platform Presence\n{hits} total platform matches across {cp.get('usernames_searched', 0)} username(s).")
        parts.append("")
    
    # Assessment
    pf = report.get("public_figure", {})
    parts.append(f"## Overall Assessment\nSubject classification: **{pf.get('level', 'UNKNOWN').replace('_', ' ')}** ({pf.get('confidence', 'LOW')} confidence).")
    
    return "\n".join(parts)
