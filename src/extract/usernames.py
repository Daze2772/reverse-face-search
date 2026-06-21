"""Username extraction from social media profile URLs."""

import re
import logging
from typing import List, Dict, Set, Optional
from urllib.parse import urlparse

logger = logging.getLogger("extract")


class UsernameExtractor:
    """Extract usernames/handles from social profile URLs using platform-specific patterns."""

    # Platform-specific regex patterns for username extraction
    PLATFORM_PATTERNS = {
        "instagram": [
            r"instagram\.com/([a-zA-Z0-9_.]{1,30})(?:[/?#]|$)",
        ],
        "linkedin": [
            r"linkedin\.com/in/([a-zA-Z0-9\-%]{3,100})(?:[/?#]|$)",
            r"linkedin\.com/company/([a-zA-Z0-9\-%]{3,100})(?:[/?#]|$)",
        ],
        "twitter": [
            r"twitter\.com/([a-zA-Z0-9_]{1,15})(?:[/?#]|$)",
        ],
        "x.com": [
            r"x\.com/([a-zA-Z0-9_]{1,15})(?:[/?#]|$)",
        ],
        "facebook": [
            r"facebook\.com/([a-zA-Z0-9.]{5,50})(?:[/?#]|$)",
        ],
        "tiktok": [
            r"tiktok\.com/@([a-zA-Z0-9_.]{2,24})(?:[/?#]|$)",
        ],
        "reddit": [
            r"reddit\.com/u(?:ser)?/([a-zA-Z0-9_-]{3,20})(?:[/?#]|$)",
        ],
        "github": [
            r"github\.com/([a-zA-Z0-9](?:[a-zA-Z0-9]|-(?!-)){1,38})(?:[/?#]|$)",
        ],
        "youtube": [
            r"youtube\.com/@([a-zA-Z0-9_.]{3,30})(?:[/?#]|$)",
            r"youtube\.com/channel/([a-zA-Z0-9_-]{24})(?:[/?#]|$)",
            r"youtube\.com/user/([a-zA-Z0-9]{3,30})(?:[/?#]|$)",
        ],
        "pinterest": [
            r"pinterest\.com/([a-zA-Z0-9]{3,30})(?:[/?#]|$)",
        ],
        "vsco": [
            r"vsco\.co/([a-zA-Z0-9_.]{1,30})(?:[/?#]|$)",
        ],
        "snapchat": [
            r"snapchat\.com/add/([a-zA-Z0-9_.-]{3,30})(?:[/?#]|$)",
        ],
        "medium": [
            r"medium\.com/@([a-zA-Z0-9]{1,30})(?:[/?#]|$)",
        ],
        "tumblr": [
            r"tumblr\.com/([a-zA-Z0-9-]{1,50})(?:[/?#]|$)",
        ],
        "twitch": [
            r"twitch\.tv/([a-zA-Z0-9_]{4,25})(?:[/?#]|$)",
        ],
        "onlyfans": [
            r"onlyfans\.com/([a-zA-Z0-9_]{3,30})(?:[/?#]|$)",
        ],
    }

    # Generic fallback pattern for unknown social-like URLs
    GENERIC_PATTERNS = [
        r"/(?:@|u/|user/|profile/|in/)([a-zA-Z0-9_.-]{2,30})(?:[/?#]|$)",
    ]

    def extract_from_clusters(self, clusters: Dict, candidate_names: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Extract usernames from clustered URLs. Returns deduplicated list, scored by name match.
        
        Args:
            clusters: Clustered URL data
            candidate_names: Optional list of person names extracted from search results
        """
        all_usernames: Dict[str, Dict] = {}  # username → {username, platforms}

        # Get social URLs from clusters
        social_urls = []
        if "categories" in clusters:
            social_urls = clusters["categories"].get("social_media", {}).get("urls", [])
        elif "social_media" in clusters:
            social_urls = clusters["social_media"].get("urls", [])

        for entry in social_urls:
            url = entry.get("url", "")
            results = self.extract_from_url(url)
            for result in results:
                uname = result["username"]
                platform = result["platform"]

                if uname in all_usernames:
                    if platform not in all_usernames[uname]["platforms"]:
                        all_usernames[uname]["platforms"].append(platform)
                        all_usernames[uname]["urls"].append(url)
                else:
                    all_usernames[uname] = {
                        "username": uname,
                        "platforms": [platform],
                        "urls": [url],
                    }

        # Score and filter usernames
        result_list = list(all_usernames.values())
        for entry in result_list:
            base_score = self.score_username_quality(entry)
            # Cross-score against candidate names if available
            name_score = 0.0
            if candidate_names:
                from .names import score_username_against_names
                name_score = score_username_against_names(entry["username"], candidate_names)
            entry["quality_score"] = round(base_score, 2)
            entry["name_match_score"] = round(name_score, 2)
            # Combined: quality filters orgs, name_match boosts real people
            entry["combined_score"] = round(base_score * 0.4 + name_score * 0.6, 2)

        # Filter: require either good quality OR name match
        filtered = [
            e for e in result_list
            if e["combined_score"] >= 0.25
        ]
        filtered.sort(key=lambda x: (x["combined_score"], len(x["platforms"])), reverse=True)

        # Split into high-confidence (name-matched) and low-confidence
        high_conf = [e for e in filtered if e["name_match_score"] >= 0.3]
        low_conf = [e for e in filtered if e["name_match_score"] < 0.3]

        logger.info(
            f"Extracted {len(result_list)} usernames → "
            f"{len(high_conf)} high-confidence (name-matched), "
            f"{len(low_conf)} low-confidence, "
            f"{len(result_list) - len(filtered)} filtered out"
        )
        return high_conf if high_conf else filtered[:10]  # Return best matches, fall back to top 10

    def extract_from_url(self, url: str) -> List[Dict[str, str]]:
        """Extract usernames from a single URL. Returns list of {username, platform}."""
        results = []
        url_lower = url.lower()

        # Try platform-specific patterns
        for platform, patterns in self.PLATFORM_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, url_lower, re.IGNORECASE)
                if match:
                    username = match.group(1)
                    # Filter out non-username path segments
                    if self._is_valid_username(username, platform):
                        results.append({"username": username, "platform": platform})
                        break  # One match per platform per URL

        # If no platform-specific match, try generic
        if not results:
            for pattern in self.GENERIC_PATTERNS:
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    username = match.group(1)
                    if self._is_valid_username(username, "unknown"):
                        results.append({"username": username, "platform": "unknown"})
                    break

        return results

    def _is_valid_username(self, username: str, platform: str) -> bool:
        """Check if extracted string looks like a valid username, not a path segment."""
        # Common false positives
        invalid = {
            "about", "login", "signup", "register", "help", "terms", "privacy",
            "settings", "search", "explore", "home", "discover", "notifications",
            "messages", "api", "blog", "jobs", "press", "legal", "p", "in",
            "account", "accounts", "photo", "photos", "post", "posts", "share",
            "hashtag", "tagged", "reel", "reels", "stories", "story", "feed",
            "watch", "shorts", "library", "subscriptions", "channel", "c",
            "embed", "follow", "following", "followers", "null", "undefined",
            "company", "school", "groups", "events", "marketplace", "friends",
            "ajax", "dialog", "oauth", "callback",
        }

        username_lower = username.lower()
        if username_lower in invalid:
            return False

        # Must be 1-100 chars
        if len(username) < 1 or len(username) > 100:
            return False

        # Must not be purely numeric (profile IDs)
        if username.isdigit():
            return False

        # Must not look like a random hash/ID
        if re.match(r'^[a-f0-9]{24,}$', username_lower):
            return False

        # Filter out obvious news/media organization handles
        if self._is_org_handle(username_lower):
            return False

        return True

    def _is_org_handle(self, username: str) -> bool:
        """Check if username looks like a news/media organization, not a person."""
        org_patterns = [
            r'(?:^|_)news(?:_|$|\d)', r'(?:^|_)press(?:_|$)', r'(?:^|_)daily(?:_|$)',
            r'(?:^|_)times(?:_|$)', r'(?:^|_)post(?:_|$)', r'(?:^|_)gazette(?:_|$)',
            r'(?:^|_)chronicle(?:_|$)', r'(?:^|_)journal(?:_|$)', r'(?:^|_)today(?:_|$)',
            r'(?:^|_)now(?:_|$)', r'(?:^|_)media(?:_|$)', r'(?:^|_)tv(?:_|\d|$)',
            r'(?:^|_)radio(?:_|$)', r'(?:^|_)magazine(?:_|$)', r'(?:^|_)report(?:_|$)',
            r'(?:^|_)observer(?:_|$)', r'(?:^|_)guardian(?:_|$)', r'(?:^|_)telegraph(?:_|$)',
            r'(?:^|_)tribune(?:_|$)', r'(?:^|_)herald(?:_|$)', r'(?:^|_)mirror(?:_|$)',
            r'(?:^|_)star(?:_|$)', r'(?:^|_)express(?:_|$)', r'(?:^|_)mail(?:_|$)',
            r'(?:^|_)globe(?:_|$)', r'(?:^|_)buzzfeed', r'(?:^|_)cnn',
            r'(?:^|_)bbc', r'(?:^|_)nbc', r'(?:^|_)abc(?:_|\d|news|$)',
            r'(?:^|_)cbs', r'(?:^|_)fox(?:_|\d|news|$)',
            r'(?:^|_)reuters', r'(?:^|_)associatedpress', r'(?:^|_)ap(?:_|news|$)',
            r'(?:^|_)bloomberg', r'(?:^|_)wsj', r'(?:^|_)nytimes',
            r'(?:^|_)washingtonpost', r'(?:^|_)huffpost', r'(?:^|_)huffingtonpost',
            r'(?:^|_)vice(?:_|news|$)', r'(?:^|_)vox(?:_|\.com|$)',
            r'(?:^|_)politico', r'(?:^|_)axios', r'(?:^|_)thehill',
            r'(?:^|_)businessinsider', r'(?:^|_)forbes', r'(?:^|_)fortune',
            r'(?:^|_)techcrunch', r'(?:^|_)theverge', r'(?:^|_)wired',
            r'(?:^|_)rollingstone', r'(?:^|_)billboard', r'(?:^|_)variety',
            r'(?:^|_)hollywoodreporter', r'(?:^|_)deadline', r'(?:^|_)indiewire',
            r'(?:^|_)people(?:_|mag|$)', r'(?:^|_)usweekly', r'(?:^|_)tmz',
            r'(?:^|_)time(?:_|mag|out|$)', r'(?:^|_)newsweek', r'(?:^|_)newyorker',
            r'(?:^|_)esquire', r'(?:^|_)gq(?:_|mag|$)', r'(?:^|_)vogue',
            r'(?:^|_)vanityfair', r'(?:^|_)cosmopolitan', r'(?:^|_)elle',
            r'(?:^|_)sportsillustrated', r'(?:^|_)espn', r'(?:^|_)bleacherreport',
            r'(?:^|_)nationalgeographic', r'(?:^|_)natgeo',
        ]
        for pattern in org_patterns:
            if re.search(pattern, username):
                return True
        return False

    def score_username_quality(self, username_entry: Dict) -> float:
        """Score a username's likelihood of being the actual person (not an org posting about them).
        
        Higher scores = more likely to be the person's real account.
        """
        score = 1.0
        username = username_entry.get("username", "").lower()
        platforms = username_entry.get("platforms", [])

        # Penalize org-like handles
        if self._is_org_handle(username):
            score -= 0.8

        # Bonus for appearing on multiple platforms (real people cross-post)
        if len(platforms) >= 3:
            score += 0.6
        elif len(platforms) >= 2:
            score += 0.3

        # Bonus for name-like patterns (firstname_lastname, firstname-lastname)
        if re.search(r'^[a-z]+[._-][a-z]+$', username):
            score += 0.3

        # Penalize all-numeric suffixes (often bots/fan pages)
        if re.search(r'\d{3,}$', username):
            score -= 0.3

        # Penalize very short handles (often brands)
        if len(username) <= 4:
            score -= 0.2

        # Cap at 0.0 - 2.0
        return max(0.0, min(2.0, score))
