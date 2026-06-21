"""Wikipedia knowledge extraction — fetch summaries, infoboxes, bio details.

Now backed by :class:`~src.cache.TTLDiskCache` so repeat lookups are free.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("intel.wikipedia")

WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "ReverseFaceSearch/2.0 (research tool; contact@example.com)"

# Filled by :mod:`src.search_manager` at startup so the lookup helpers can
# share the project-wide cache without import cycles.
_cache = None


def configure_cache(cache) -> None:
    """Inject a :class:`TTLDiskCache` instance for memoising results."""
    global _cache
    _cache = cache


async def search_wikipedia(name: str) -> Optional[Dict[str, Any]]:
    """Search Wikipedia for ``name``; returns structured page data or None."""
    if not name or len(name) < 3:
        return None

    if _cache:
        cached = await _cache.get("wikipedia", name.lower())
        if cached is not None:
            logger.debug(f"Wikipedia cache hit: {name}")
            return cached

    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": name,
                "format": "json",
                "srlimit": 5,
            }
            resp = await client.get(WIKI_API, params=params)
            data = resp.json()

            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                logger.info(f"No Wikipedia results for: {name}")
                if _cache:
                    await _cache.set("wikipedia", name.lower(), {"found": False})
                return None

            best_title = _pick_best_title(name, search_results)
            page = await _fetch_page_data(client, best_title)

    except Exception as e:
        logger.warning(f"Wikipedia search error for '{name}': {e}")
        return None

    if _cache and page:
        await _cache.set("wikipedia", name.lower(), page)
    return page


def _pick_best_title(name: str, search_results: List[Dict[str, Any]]) -> str:
    """Score search results to find the most likely person page.

    Heuristics:
      * Exact token match on the title wins.
      * Reject obvious non-person pages ("List of...", "Characters of...",
        "Episode 1", etc.) unless nothing else matches.
    """
    name_lower = name.lower()
    name_parts = set(name_lower.split())

    def is_list_page(title: str) -> bool:
        t = title.lower()
        return any(s in t for s in ("characters of", "list of", "episode",
                                    "season ", "discography", "filmography"))

    # Pass 1: exact token match
    for r in search_results:
        title = r["title"]
        title_parts = set(re.sub(r'[()]', '', title.lower()).split())
        if title_parts == name_parts:
            return title

    # Pass 2: all name parts contained, no list-page disqualifier
    for r in search_results:
        title = r["title"]
        title_lower = title.lower()
        if all(part in title_lower for part in name_parts) and not is_list_page(title):
            return title

    # Pass 3: any result without list-page markers
    for r in search_results:
        if not is_list_page(r["title"]):
            return r["title"]

    # Last resort
    return search_results[0]["title"]


async def _fetch_page_data(client: httpx.AsyncClient, title: str) -> Dict[str, Any]:
    """Fetch detailed page data: extract, infobox categories, image, page URL."""
    params = {
        "action": "query",
        "prop": "extracts|pageimages|categories|info",
        "exintro": 1,
        "explaintext": 1,
        "exsectionformat": "plain",
        "pithumbsize": 300,
        "cllimit": 20,
        "inprop": "url",
        "titles": title,
        "format": "json",
        "redirects": 1,
    }
    resp = await client.get(WIKI_API, params=params)
    data = resp.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return {"title": title, "found": False}

    page = next(iter(pages.values()))
    extract = page.get("extract", "")
    thumbnail = page.get("thumbnail", {}).get("source", "")
    page_url = page.get("fullurl", f"https://en.wikipedia.org/wiki/{quote(title)}")
    page_id = page.get("pageid", "")

    categories = [
        c.get("title", "").replace("Category:", "")
        for c in page.get("categories", [])
    ]
    facts = _infer_facts(categories, extract)
    summary = extract.split("\n\n")[0] if extract else ""

    result = {
        "title": title,
        "found": True,
        "summary": summary[:2000],
        "thumbnail": thumbnail,
        "page_url": page_url,
        "page_id": page_id,
        "categories": categories[:15],
        "facts": facts,
    }
    logger.info(f"Wikipedia: {title} — {len(categories)} categories, {len(facts)} facts")
    return result


def _infer_facts(categories: List[str], extract: str) -> Dict[str, Any]:
    """Infer structured facts from categories and extract text."""
    facts: Dict[str, Any] = {}
    category_text = " ".join(categories).lower()

    nationalities = {
        "american": "American", "british": "British", "canadian": "Canadian",
        "french": "French", "german": "German", "italian": "Italian",
        "spanish": "Spanish", "australian": "Australian", "japanese": "Japanese",
        "chinese": "Chinese", "indian": "Indian", "russian": "Russian",
        "brazilian": "Brazilian", "mexican": "Mexican", "korean": "Korean",
        "dutch": "Dutch", "swedish": "Swedish", "norwegian": "Norwegian",
        "turkish": "Turkish", "iranian": "Iranian", "pakistani": "Pakistani",
        "nigerian": "Nigerian", "egyptian": "Egyptian", "south african": "South African",
        "irish": "Irish", "scottish": "Scottish", "welsh": "Welsh",
        "polish": "Polish", "ukrainian": "Ukrainian", "greek": "Greek",
    }
    for key, label in nationalities.items():
        if key in category_text:
            facts["nationality"] = label
            break

    professions = {
        "actor": "Actor", "actress": "Actress", "politician": "Politician",
        "musician": "Musician", "singer": "Singer", "writer": "Writer",
        "artist": "Artist", "athlete": "Athlete", "scientist": "Scientist",
        "physicist": "Physicist", "director": "Director", "producer": "Producer",
        "comedian": "Comedian", "model": "Model", "journalist": "Journalist",
        "businessman": "Businessperson", "entrepreneur": "Entrepreneur",
        "doctor": "Doctor", "lawyer": "Lawyer", "professor": "Professor",
        "engineer": "Engineer", "architect": "Architect", "designer": "Designer",
        "philosopher": "Philosopher", "economist": "Economist", "historian": "Historian",
    }
    for key, label in professions.items():
        if key in category_text:
            if "profession" not in facts:
                facts["profession"] = label
            else:
                facts["profession"] += f", {label}"

    birth = re.search(r'(?:born|b\.)\s*(\d{4})', extract, re.IGNORECASE)
    if birth:
        facts["birth_year"] = birth.group(1)
    death = re.search(r'(?:died|d\.)\s*(\d{4})', extract, re.IGNORECASE)
    if death:
        facts["death_year"] = death.group(1)

    if extract:
        facts["known_for"] = extract.split(".")[0][:200].strip()
    return facts


def format_person_summary(wiki_data: Dict[str, Any]) -> str:
    """Format Wikipedia data into a human-readable summary."""
    if not wiki_data or not wiki_data.get("found"):
        return "No Wikipedia entry found."

    parts = [f"**{wiki_data['title']}**"]
    facts = wiki_data.get("facts", {})
    if facts.get("nationality"):
        parts.append(f"Nationality: {facts['nationality']}")
    if facts.get("profession"):
        parts.append(f"Profession: {facts['profession']}")
    if facts.get("birth_year"):
        birth = facts["birth_year"]
        death = facts.get("death_year", "")
        parts.append(f"Lived: {birth}–{death}" if death else f"Born: {birth}")
    if wiki_data.get("summary"):
        parts.append(f"\n{wiki_data['summary']}")
    if wiki_data.get("page_url"):
        parts.append(f"\nWikipedia: {wiki_data['page_url']}")
    return "\n".join(parts)
