"""Domain-based URL clustering for reverse search results."""

import logging
from typing import List, Dict, Any
from urllib.parse import urlparse

from ..config import AppConfig

logger = logging.getLogger("cluster")


class ClusterParser:
    """Parse and cluster result URLs by domain pattern."""

    CATEGORIES = [
        "social_media",
        "news_media",
        "forums_communities",
        "personal_blogs",
        "academic",
        "ecommerce",
        "image_hosting",
        "other",
    ]

    def __init__(self, config: AppConfig):
        self.config = config
        self.social_domains = config.clustering.social_domains
        self.news_domains = config.clustering.news_domains
        self.forum_domains = config.clustering.forum_domains
        self.blog_domains = config.clustering.blog_domains

    def cluster(self, url_entries: List[Dict[str, str]]) -> Dict[str, Any]:
        """Cluster URL entries by domain category. Deduplicates by URL."""
        # Initialize category buckets
        clusters: Dict[str, Any] = {
            cat: {"urls": [], "count": 0, "confidence": 0.0}
            for cat in self.CATEGORIES
        }

        seen_urls = set()

        for entry in url_entries:
            url = entry.get("url", "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]

            category = self._classify_domain(domain)
            entry_with_domain = {**entry, "domain": domain}
            clusters[category]["urls"].append(entry_with_domain)
            clusters[category]["count"] = len(clusters[category]["urls"])

        # Calculate confidence scores (heuristic)
        for cat in self.CATEGORIES:
            count = clusters[cat]["count"]
            if count > 10:
                clusters[cat]["confidence"] = 0.9
            elif count > 5:
                clusters[cat]["confidence"] = 0.7
            elif count > 0:
                clusters[cat]["confidence"] = 0.4

        # Build sub-clusters for social media (per platform)
        social_subs = self._sub_cluster_social(clusters["social_media"]["urls"])

        logger.info(
            f"Clustered {len(url_entries)} URLs: "
            + ", ".join(f"{cat}={clusters[cat]['count']}" for cat in self.CATEGORIES if clusters[cat]['count'] > 0)
        )

        return {
            "categories": clusters,
            "social_sub_clusters": social_subs,
            "total_unique_urls": len(seen_urls),
        }

    def _classify_domain(self, domain: str) -> str:
        """Classify a domain into a category."""
        # Social media
        for platform, patterns in self.social_domains.items():
            for pattern in patterns:
                if pattern in domain:
                    return "social_media"

        # News / media
        for pattern in self.news_domains:
            if pattern in domain:
                return "news_media"

        # Forums / communities
        for pattern in self.forum_domains:
            if pattern in domain:
                return "forums_communities"

        # Personal blogs
        for pattern in self.blog_domains:
            if pattern in domain:
                return "personal_blogs"

        # Academics
        academic_tlds = [".edu", ".ac.", ".gov", ".org"]
        for tld in academic_tlds:
            if tld in domain:
                return "academic"

        # Image hosting
        image_hosts = ["imgur.com", "flickr.com", "500px.com", "deviantart.com",
                       "photobucket.com", "imageshack.com", "tinypic.com",
                       "i.imgur.com", "cdn", "static", "assets"]
        for host in image_hosts:
            if host in domain:
                return "image_hosting"

        # E-commerce
        shop_domains = ["amazon.", "ebay.", "etsy.", "shopify.", "aliexpress.",
                        "walmart.", "target.", "bestbuy."]
        for sd in shop_domains:
            if sd in domain:
                return "ecommerce"

        return "other"

    def _sub_cluster_social(self, social_urls: List[Dict]) -> Dict[str, List[Dict]]:
        """Split social URLs into per-platform sub-clusters."""
        subs: Dict[str, List[Dict]] = {}
        platform_labels = {
            "instagram.com": "Instagram",
            "linkedin.com": "LinkedIn",
            "twitter.com": "Twitter",
            "x.com": "Twitter/X",
            "facebook.com": "Facebook",
            "fb.com": "Facebook",
            "tiktok.com": "TikTok",
            "vsco.co": "VSCO",
            "snapchat.com": "Snapchat",
            "reddit.com": "Reddit",
            "pinterest.com": "Pinterest",
            "youtube.com": "YouTube",
            "github.com": "GitHub",
        }

        for entry in social_urls:
            domain = entry.get("domain", "")
            platform = None
            for key, label in platform_labels.items():
                if key in domain:
                    platform = label
                    break
            if not platform:
                platform = domain

            if platform not in subs:
                subs[platform] = []
            subs[platform].append(entry)

        return subs
