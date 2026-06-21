"""Yandex Images reverse search engine handler."""

import asyncio
import logging
from typing import List, Dict, Optional
from urllib.parse import quote

from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.yandex")


class YandexEngine(BaseSearchEngine):
    """Reverse image search via Yandex Images (URL-based)."""

    OWN_DOMAINS = ["yandex.com", "yandex.ru", "yandex.net", "ya.ru", "yastatic.net"]

    def __init__(self, config):
        super().__init__(config, "yandex")

    async def _do_search(
        self,
        page: Page,
        image_path: str,
        image_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        # ``image_url`` presence is enforced by the base class.
        search_url = (
            "https://yandex.com/images/search"
            f"?rpt=imageview&url={quote(image_url, safe='')}"
        )
        logger.info(f"[yandex] Searching: {search_url[:120]}...")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        await self.wait_for_results(page)

        # Try to coax more results out — Yandex loads lazily.
        try:
            buttons = page.locator('button, a.button, .more-button, [data-action="more"]')
            count = await buttons.count()
            for i in range(min(count, 3)):
                try:
                    await buttons.nth(i).click(timeout=1500)
                    await asyncio.sleep(0.8)
                except Exception:
                    pass
        except Exception:
            pass

        await asyncio.sleep(1)
        return await self.extract_external_links(page)
