"""Browser pool — share a single Playwright process across engines.

The original code spun up a fresh Playwright + Chromium process **per engine
per search**. With three engines that meant three Chromium processes for every
upload. This pool keeps one Playwright runtime and one Chromium browser for
the duration of a search; each engine just gets its own browsing context.
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright

logger = logging.getLogger("engines.pool")


class BrowserPool:
    """Single-search browser lifetime helper.

    Usage:
        async with BrowserPool.session(config) as pool:
            browser = pool.browser
            ...  # engines share `browser`
    """

    def __init__(self, playwright: Playwright, browser: Browser):
        self._playwright = playwright
        self._browser = browser

    @property
    def browser(self) -> Browser:
        return self._browser

    @classmethod
    @asynccontextmanager
    async def session(cls, config):
        """Async context manager that yields a fully configured pool."""
        playwright = await async_playwright().start()
        try:
            launch_args = {
                "headless": config.browser.headless,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            proxy_url = config.proxy.residential_url
            if config.proxy.enabled and proxy_url:
                launch_args["proxy"] = {"server": proxy_url}

            browser = await playwright.chromium.launch(**launch_args)
            try:
                yield cls(playwright, browser)
            finally:
                try:
                    await browser.close()
                except Exception:
                    logger.debug("Browser close failed", exc_info=True)
        finally:
            try:
                await playwright.stop()
            except Exception:
                logger.debug("Playwright stop failed", exc_info=True)
