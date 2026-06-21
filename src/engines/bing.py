"""Bing Images reverse image search engine handler."""

import asyncio
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.bing")


class BingEngine(BaseSearchEngine):
    """Reverse image search via Bing Visual Search (URL-based)."""

    OWN_DOMAINS = ["bing.com", "microsoft.com", "msn.com", "msedge.net",
                   "live.com", "office.com", "office.net"]

    def __init__(self, config):
        super().__init__(config, "bing")

    async def _do_search(
        self,
        page: Page,
        image_path: str,
        image_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        bing_url = (
            "https://www.bing.com/images/search"
            f"?view=detailv2&iss=sbi&q=imgurl:{quote(image_url, safe='')}"
        )
        logger.info(f"[bing] Searching: {bing_url[:120]}...")

        await page.goto(bing_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        await self.wait_for_results(page)
        return await self.extract_external_links(page)
