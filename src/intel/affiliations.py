"""Affiliation and context extraction from search results — NER on titles and snippets."""

import re
import logging
from typing import List, Dict, Set
from collections import Counter

logger = logging.getLogger("intel.affiliations")


# Known organizations, entities, and location patterns
ORGANIZATIONS = {
    "united nations": "United Nations",
    "european union": "European Union",
    "nato": "NATO",
    "fbi": "FBI",
    "cia": "CIA",
    "nsa": "NSA",
    "white house": "White House",
    "congress": "US Congress",
    "senate": "US Senate",
    "pentagon": "Pentagon",
    "state department": "US State Department",
    "world bank": "World Bank",
    "imf": "IMF",
    "who": "WHO",
    "unicef": "UNICEF",
    "red cross": "Red Cross",
    "doctors without borders": "Doctors Without Borders",
    "amnesty international": "Amnesty International",
    "greenpeace": "Greenpeace",
    "wikileaks": "WikiLeaks",
    "anonymous": "Anonymous",
    # Media
    "cnn": "CNN", "bbc": "BBC", "fox news": "Fox News", "msnbc": "MSNBC",
    "new york times": "New York Times", "washington post": "Washington Post",
    "wall street journal": "Wall Street Journal", "reuters": "Reuters",
    "associated press": "Associated Press", "bloomberg": "Bloomberg",
    "the guardian": "The Guardian", "al jazeera": "Al Jazeera",
    # Tech
    "google": "Google", "apple": "Apple", "microsoft": "Microsoft",
    "amazon": "Amazon", "facebook": "Facebook", "meta": "Meta",
    "twitter": "Twitter", "openai": "OpenAI", "tesla": "Tesla",
    "spacex": "SpaceX", "nvidia": "NVIDIA",
    # Universities
    "harvard": "Harvard University", "mit": "MIT", "stanford": "Stanford",
    "oxford": "Oxford University", "cambridge": "Cambridge University",
    "yale": "Yale University", "princeton": "Princeton",
    # Political parties
    "democratic party": "Democratic Party", "republican party": "Republican Party",
    "labour party": "Labour Party", "conservative party": "Conservative Party",
}

TOPICS = {
    "climate change": "Climate Change", "global warming": "Global Warming",
    "artificial intelligence": "Artificial Intelligence", "machine learning": "Machine Learning",
    "cryptocurrency": "Cryptocurrency", "bitcoin": "Bitcoin", "blockchain": "Blockchain",
    "covid": "COVID-19", "pandemic": "Pandemic",
    "election": "Elections", "democracy": "Democracy",
    "immigration": "Immigration", "healthcare": "Healthcare",
    "education": "Education", "economy": "Economy",
    "human rights": "Human Rights", "civil rights": "Civil Rights",
    "privacy": "Privacy", "surveillance": "Surveillance",
    "cybersecurity": "Cybersecurity", "hacking": "Hacking",
    "space exploration": "Space Exploration",
    "renewable energy": "Renewable Energy", "solar": "Solar Energy",
    "abortion": "Abortion", "gun control": "Gun Control",
    "tax": "Taxation", "inflation": "Inflation",
}

LOCATIONS = {
    "new york": "New York, USA", "los angeles": "Los Angeles, USA",
    "washington": "Washington DC, USA", "chicago": "Chicago, USA",
    "london": "London, UK", "paris": "Paris, France",
    "berlin": "Berlin, Germany", "moscow": "Moscow, Russia",
    "beijing": "Beijing, China", "tokyo": "Tokyo, Japan",
    "delhi": "New Delhi, India", "sydney": "Sydney, Australia",
    "toronto": "Toronto, Canada", "mexico city": "Mexico City, Mexico",
    "sao paulo": "São Paulo, Brazil", "dubai": "Dubai, UAE",
    "singapore": "Singapore", "seoul": "Seoul, South Korea",
    "brussels": "Brussels, Belgium", "geneva": "Geneva, Switzerland",
    "amsterdam": "Amsterdam, Netherlands", "rome": "Rome, Italy",
    "madrid": "Madrid, Spain", "vienna": "Vienna, Austria",
    "istanbul": "Istanbul, Turkey", "cairo": "Cairo, Egypt",
    "lagos": "Lagos, Nigeria", "nairobi": "Nairobi, Kenya",
    "johannesburg": "Johannesburg, South Africa",
    "tel aviv": "Tel Aviv, Israel", "riyadh": "Riyadh, Saudi Arabia",
    "tehran": "Tehran, Iran", "baghdad": "Baghdad, Iraq",
    "kabul": "Kabul, Afghanistan", "kyiv": "Kyiv, Ukraine",
    "warsaw": "Warsaw, Poland", "stockholm": "Stockholm, Sweden",
    "oslo": "Oslo, Norway", "copenhagen": "Copenhagen, Denmark",
    "helsinki": "Helsinki, Finland", "lisbon": "Lisbon, Portugal",
    "athens": "Athens, Greece", "budapest": "Budapest, Hungary",
    "prague": "Prague, Czech Republic",
}


def extract_affiliations(engine_results: Dict[str, Dict]) -> Dict[str, List[str]]:
    """Extract organizations, locations, and topics from all search result text."""
    all_text = ""
    
    for engine_name, result in engine_results.items():
        urls = result.get("urls", [])
        for entry in urls:
            title = entry.get("title", "")
            snippet = entry.get("snippet", "")
            url = entry.get("url", "")
            all_text += f" {title} {snippet} {url} "
    
    text_lower = all_text.lower()
    
    orgs = Counter()
    locations = Counter()
    topics = Counter()
    
    # Extract organizations
    for key, label in ORGANIZATIONS.items():
        if key in text_lower:
            orgs[label] += text_lower.count(key)
    
    # Filter out common platform noise that appears in URLs but isn't a real affiliation
    PLATFORM_NOISE = {
        "facebook", "twitter", "instagram", "google", "youtube", "tiktok",
        "pinterest", "linkedin", "reddit", "snapchat", "whatsapp",
        "amazon", "apple", "microsoft", "netflix", "spotify",
        "wikipedia", "wikimedia", "imdb", "ebay", "etsy", "yahoo", "msn", "bing",
        "cia", "fbi", "nsa", "meta", "white house", "congress", "senate",
    }
    orgs_filtered = Counter({k: v for k, v in orgs.items() if k.lower() not in PLATFORM_NOISE})
    
    # Extract locations
    for key, label in LOCATIONS.items():
        if key in text_lower:
            locations[label] += text_lower.count(key)
    
    # Extract topics
    for key, label in TOPICS.items():
        if key in text_lower:
            topics[label] += text_lower.count(key)
    
    # Extract URLs by domain as implicit organizations
    domains = Counter()
    domain_pattern = re.compile(r'https?://(?:www\.)?([^/]+)')
    for match in domain_pattern.finditer(all_text):
        domain = match.group(1).lower()
        if any(skip in domain for skip in ['google', 'yandex', 'bing', 'tmpfiles', 'file.io', '0x0.st',
                                              'yastatic', 'gstatic', 'cloudfront', 'cdn', 'akamai',
                                              'doubleclick', 'facebook.com/plugins']):
            continue
        # Clean domain
        domain = domain.split('.')[0] if domain.count('.') <= 1 else '.'.join(domain.split('.')[1:])
        domains[domain] += 1
    
    result = {
        "organizations": [{"name": name, "count": count} for name, count in orgs_filtered.most_common(10)],
        "locations": [{"name": name, "count": count} for name, count in locations.most_common(10)],
        "topics": [{"name": name, "count": count} for name, count in topics.most_common(10)],
        "related_domains": [{"domain": domain, "count": count} for domain, count in domains.most_common(15)],
    }
    
    total = len(orgs_filtered) + len(locations) + len(topics) + len(domains)
    logger.info(f"Affiliations extracted: {len(orgs_filtered)} orgs, {len(locations)} locations, {len(topics)} topics, {len(domains)} domains")
    
    return result if total > 0 else _empty_result()


def _empty_result() -> Dict[str, List]:
    return {"organizations": [], "locations": [], "topics": [], "related_domains": []}
