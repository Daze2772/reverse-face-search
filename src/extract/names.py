"""Name extraction from search result URLs and titles."""

import re
import logging
from typing import List, Dict, Set, Optional
from urllib.parse import unquote

logger = logging.getLogger("extract.names")


# Common Wikipedia URL patterns for person articles
WIKI_PERSON_PATTERNS = [
    re.compile(r'wikipedia\.org/wiki/([A-Z][a-z]+(?:_[A-Z][a-z]+)+)'),  # Cooper_Barnes → Cooper Barnes
    re.compile(r'wikipedia\.org/wiki/([A-Z][a-z]+_[A-Z][a-z]+)'),
]

# Name patterns in titles/snippets
NAME_TITLE_PATTERNS = [
    # "Cooper Barnes - Wikipedia" or "Cooper Barnes | Actor"
    re.compile(r'([A-Z][a-z]+ [A-Z][a-z]+(?: [A-Z][a-z]+)?)(?:\s*[-–|—])'),
    # "Who is Cooper Barnes?" or "About Cooper Barnes"
    re.compile(r'(?:about|who is|profile of|biography of)\s+([A-Z][a-z]+ [A-Z][a-z]+(?: [A-Z][a-z]+)?)', re.IGNORECASE),
]

# Social handle → name conversion helpers
def name_to_handle_variants(name: str) -> List[str]:
    """Generate possible social handle variations from a person name.
    'Cooper Barnes' → ['cooperbarnes', 'cooper_barnes', 'cooper-barnes', 'cooper', 'cooperb']
    """
    parts = name.lower().split()
    variants = []
    
    # Full name concatenated
    variants.append(''.join(parts))
    variants.append('_'.join(parts))
    variants.append('-'.join(parts))
    variants.append('.'.join(parts))
    
    # First name only
    if len(parts) >= 1:
        variants.append(parts[0])
    
    # First name + last initial
    if len(parts) >= 2:
        variants.append(parts[0] + parts[1][0])
        variants.append(parts[0][0] + parts[1])
    
    # "thereal" + name
    variants.append('thereal' + ''.join(parts))
    variants.append('real' + ''.join(parts))
    
    # With "official" prefix
    variants.append('official' + parts[0] + (parts[1] if len(parts) > 1 else ''))
    
    return list(set(variants))


def extract_names_from_results(engine_results: Dict[str, Dict]) -> List[str]:
    """Extract candidate person names from all engine search results.
    
    Looks at:
    - Wikipedia URL slugs
    - Result titles with name patterns
    - Snippets/descriptions
    
    Returns deduplicated list of possible full names.
    """
    names: Set[str] = set()
    
    for engine_name, result in engine_results.items():
        urls = result.get("urls", [])
        
        for entry in urls:
            url = entry.get("url", "")
            title = entry.get("title", "")
            snippet = entry.get("snippet", "")
            
            # Check Wikipedia URLs
            decoded_url = unquote(url)
            for pattern in WIKI_PERSON_PATTERNS:
                match = pattern.search(decoded_url)
                if match:
                    raw_name = match.group(1).replace('_', ' ')
                    # Filter out non-person Wikipedia articles
                    if not _is_non_person_wiki(raw_name):
                        names.add(raw_name)
                        logger.debug(f"Name from wiki URL: {raw_name}")
            
            # Check titles
            for pattern in NAME_TITLE_PATTERNS:
                match = pattern.search(title)
                if match:
                    name = match.group(1).strip()
                    if _looks_like_person_name(name):
                        names.add(name)
                        logger.debug(f"Name from title: {name}")
            
            # Also check snippet
            if snippet:
                for pattern in NAME_TITLE_PATTERNS:
                    match = pattern.search(snippet)
                    if match:
                        name = match.group(1).strip()
                        if _looks_like_person_name(name):
                            names.add(name)
    
    result_list = sorted(names)
    logger.info(f"Extracted {len(result_list)} candidate names: {result_list}")
    return result_list


def score_username_against_names(username: str, candidate_names: List[str]) -> float:
    """Score how well a username matches any extracted candidate name.
    
    Returns 0.0 (no match) to 1.0 (exact handle variant match).
    """
    if not candidate_names:
        return 0.0
    
    username_lower = username.lower().strip('@')
    best_score = 0.0
    
    for name in candidate_names:
        variants = name_to_handle_variants(name)
        
        for variant in variants:
            # Exact match
            if username_lower == variant:
                return 1.0
            
            # Contains variant
            if variant in username_lower:
                score = len(variant) / len(username_lower)
                best_score = max(best_score, score * 0.9)
            
            # Username contained in variant
            if username_lower in variant:
                score = len(username_lower) / len(variant)
                best_score = max(best_score, score * 0.7)
        
        # Fuzzy: first name matches username start
        parts = name.lower().split()
        if parts and username_lower.startswith(parts[0]):
            best_score = max(best_score, 0.5)
        
        # Fuzzy: last name matches username somewhere
        if len(parts) >= 2 and parts[1] in username_lower:
            best_score = max(best_score, 0.4)
    
    return round(best_score, 2)


def _looks_like_person_name(name: str) -> bool:
    """Heuristic check: does this look like a person name?"""
    parts = name.split()
    if len(parts) < 2 or len(parts) > 4:
        return False
    
    # Each part should start with uppercase letter
    for part in parts:
        if not part[0].isupper():
            return False
        if len(part) < 2:
            return False
    
    # At least one part must be a common first name
    has_first_name = any(part.lower() in COMMON_FIRST_NAMES for part in parts)
    if not has_first_name:
        # Allow if name comes from Wikipedia with person-indicating title context
        return False
    
    return True


# Common first names across cultures — used to validate person name extraction
COMMON_FIRST_NAMES = {
    # English / Western
    "james", "john", "robert", "michael", "william", "david", "richard", "joseph",
    "thomas", "charles", "christopher", "daniel", "matthew", "anthony", "mark",
    "donald", "steven", "paul", "andrew", "joshua", "kenneth", "kevin", "brian",
    "george", "timothy", "ronald", "edward", "jason", "jeffrey", "ryan", "jacob",
    "gary", "nicholas", "eric", "jonathan", "stephen", "larry", "justin", "scott",
    "brandon", "benjamin", "samuel", "raymond", "gregory", "frank", "alexander",
    "patrick", "jack", "dennis", "jerry", "tyler", "aaron", "jose", "adam",
    "nathan", "henry", "douglas", "zachary", "peter", "kyle", "walter", "ethan",
    "jeremy", "harold", "keith", "christian", "roger", "noah", "gerald", "carl",
    "terry", "sean", "austin", "arthur", "lawrence", "jesse", "dylan", "bryan",
    "joe", "jordan", "billy", "bruce", "albert", "willie", "gabriel", "logan",
    "alan", "juan", "wayne", "roy", "ralph", "randy", "eugene", "vincent",
    "russell", "elijah", "louis", "bobby", "philip", "johnny", "barack", "donald",
    "ted", "marco", "bernie", "joe", "kamala", "hillary", "nancy", "mitch",
    # Female
    "mary", "patricia", "jennifer", "linda", "barbara", "elizabeth", "susan",
    "jessica", "sarah", "karen", "lisa", "nancy", "betty", "margaret", "sandra",
    "ashley", "dorothy", "kimberly", "emily", "donna", "michelle", "carol",
    "amanda", "melissa", "deborah", "stephanie", "rebecca", "sharon", "laura",
    "cynthia", "kathleen", "amy", "angela", "shirley", "anna", "brenda", "pamela",
    "emma", "nicole", "helen", "samantha", "katherine", "christine", "debra",
    "rachel", "carolyn", "janet", "catherine", "maria", "olivia", "heather",
    "diane", "julie", "joyce", "victoria", "kelly", "christina", "lauren",
    "joan", "madison", "abigail", "megan", "alice", "judy", "isabella", "grace",
    "amber", "denise", "danielle", "marilyn", "beverly", "charlotte", "natalie",
    "theresa", "diana", "brittany", "doris", "mildred", "tiffany", "jane",
    # International
    "mohammed", "ali", "ahmed", "wei", "li", "yuki", "hiroshi", "takashi",
    "olga", "ivan", "dmitri", "sergei", "vladimir", "boris", "pablo", "carlos",
    "javier", "miguel", "giovanni", "marco", "francesco", "hans", "klaus",
    "pierre", "jean", "francois", "raj", "vikram", "sanjay", "kim", "park",
    "emma", "sophie", "marie", "isabelle", "ingrid", "astrid", "helga",
    # Celebrities / common
    "beyonce", "rihanna", "madonna", "oprah", "elvis", "marilyn", "prince",
    "taylor", "ariana", "selena", "justin", "shawn", "drake", "kanye",
    "brad", "leonardo", "tom", "robert", "scarlett", "angelina", "jennifer",
    "chris", "will", "morgan", "samuel", "bruce", "cooper", "pedro", "ryan",
    "keanu", "matt", "ben", "jake", "mark", "chadwick", "idris", "henry",
    "hemsworth", "cumberbatch", "dicaprio", "pitt", "cruise", "hanks", "depp",
    "clooney", "downey", "jackman", "pratt", "evans", "hemsworth", "cavill",
    "momoa", "johnson", "statham", "diesel", "rock", "willis", "stallone",
    "schwarzenegger", "liu", "chan", "li", "yen", "washington",
}


def _is_non_person_wiki(name: str) -> bool:
    """Filter out Wikipedia articles that aren't about people."""
    non_person = {
        "united states", "united kingdom", "new york", "los angeles",
        "world war", "american civil", "christmas", "thanksgiving",
        "iphone", "android", "microsoft", "google", "apple inc",
        "democratic party", "republican party", "supreme court",
    }
    name_lower = name.lower()
    for np in non_person:
        if np in name_lower:
            return True
    return False
