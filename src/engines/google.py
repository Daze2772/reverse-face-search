"""Google Lens reverse image search engine handler."""

import asyncio
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.google")


class GoogleEngine(BaseSearchEngine):
    """Reverse image search via Google Lens (URL-based)."""

    OWN_DOMAINS = ["google.com", "google.co", "gstatic.com", "googleusercontent.com",
                   "googleadservices.com", "google-analytics.com", "doubleclick.net"]

    def __init__(self, config):
        super().__init__(config, "google")

    async def _do_search(
        self,
        page: Page,
        image_path: str,
        image_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        lens_url = f"https://lens.google.com/uploadbyurl?url={quote(image_url, safe='')}"
        logger.info(f"[google] Searching: {lens_url[:120]}...")

        await page.goto(lens_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Handle cookie consent dialogs in multiple locales.
        for text in ("Accept all", "I agree", "Accept", "Alle akzeptieren",
                     "Tout accepter", "Acepto todo"):
            try:
                btn = page.locator(f'button:has-text("{text}")').first
                if await btn.count() > 0:
                    await btn.click(timeout=2000)
                    await asyncio.sleep(1)
                    break
            except Exception:
                continue

        await self.wait_for_results(page)
        return await self.extract_external_links(page)
