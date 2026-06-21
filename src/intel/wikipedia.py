"""Wikipedia knowledge extraction — fetch summaries, infoboxes, bio details."""

import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import quote, unquote

logger = logging.getLogger("intel.wikipedia")

# Wikipedia API endpoint
WIKI_API = "https://en.wikipedia.org/w/api.php"


async def search_wikipedia(name: str) -> Optional[Dict[str, Any]]:
    """Search Wikipedia for a person and extract structured data."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": "ReverseFaceSearch/2.0 (research tool; contact@example.com)"
        }) as client:
            # Search for the page
            params = {
                "action": "query",
                "list": "search",
                "srsearch": name,
                "format": "json",
                "srlimit": 3,
            }
            resp = await client.get(WIKI_API, params=params)
            data = resp.json()
            
            search_results = data.get("query", {}).get("search", [])
            if not search_results:
                logger.info(f"No Wikipedia results for: {name}")
                return None

            # Get the best match title — prefer exact name match over related articles
            best_title = None
            name_lower = name.lower()
            name_parts = set(name_lower.split())
            
            for result in search_results:
                title = result["title"]
                title_lower = title.lower()
                
                # Exact match: page title IS the person's name
                title_parts = set(title_lower.replace("(", "").replace(")", "").split())
                if title_parts == name_parts or (name_parts.issubset(title_parts) and len(title_parts) <= len(name_parts) + 2):
                    best_title = title
                    break
            
            if not best_title:
                # Fallback: title contains all name parts, not a list/characters page
                for result in search_results:
                    title = result["title"]
                    title_lower = title.lower()
                    if (all(part in title_lower for part in name_parts) 
                        and "characters of" not in title_lower
                        and "list of" not in title_lower
                        and "episode" not in title_lower):
                        best_title = title
                        break
            
            if not best_title:
                best_title = search_results[0]["title"]
            
            # Fetch page extract + infobox data
            return await _fetch_page_data(client, best_title)

    except Exception as e:
        logger.error(f"Wikipedia search error for '{name}': {e}")
        return None


async def _fetch_page_data(client, title: str) -> Dict[str, Any]:
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
    
    page = list(pages.values())[0]
    
    # Extract structured data
    extract = page.get("extract", "")
    thumbnail = page.get("thumbnail", {}).get("source", "")
    page_url = page.get("fullurl", f"https://en.wikipedia.org/wiki/{quote(title)}")
    page_id = page.get("pageid", "")
    
    # Parse categories for classification
    categories = []
    for cat in page.get("categories", []):
        cat_title = cat.get("title", "").replace("Category:", "")
        categories.append(cat_title)
    
    # Infer facts from categories and extract
    facts = _infer_facts(categories, extract)
    
    # Clean extract for summary
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
    facts = {}
    
    category_text = " ".join(categories).lower()
    
    # Nationality
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
    
    # Profession
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
    
    # Birth/death years from extract
    birth_match = re.search(r'(?:born|b\.)\s*(\d{4})', extract, re.IGNORECASE)
    if birth_match:
        facts["birth_year"] = birth_match.group(1)
    
    death_match = re.search(r'(?:died|d\.)\s*(\d{4})', extract, re.IGNORECASE)
    if death_match:
        facts["death_year"] = death_match.group(1)
    
    # Known for (first sentence of extract)
    if extract:
        first_sentence = extract.split(".")[0][:200]
        facts["known_for"] = first_sentence.strip()
    
    return facts


def format_person_summary(wiki_data: Dict[str, Any]) -> str:
    """Format Wikipedia data into a human-readable person summary."""
    if not wiki_data.get("found"):
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
        if death:
            parts.append(f"Lived: {birth}–{death}")
        else:
            parts.append(f"Born: {birth}")
    
    if wiki_data.get("summary"):
        parts.append(f"\n{wiki_data['summary']}")
    
    if wiki_data.get("page_url"):
        parts.append(f"\nWikipedia: {wiki_data['page_url']}")
    
    return "\n".join(parts)
