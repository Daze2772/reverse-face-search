"""Base engine class for reverse image search."""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger("engines")


class BaseSearchEngine(ABC):
    """Abstract base for reverse image search engine handlers."""

    def __init__(self, config, engine_name: str):
        self.config = config
        self.engine_name = engine_name
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        ]

    async def search(self, image_path: str, image_url: Optional[str] = None) -> Dict[str, Any]:
        """Public interface: launch browser, execute search, collect results.
        
        Args:
            image_path: Local path to the image file
            image_url: Optional public URL for the image (for URL-based engines)
        """
        logger.info(f"[{self.engine_name}] Starting reverse image search")

        playwright = None
        try:
            playwright = await async_playwright().start()
            browser = await self._launch_browser(playwright)
            context = await self._create_context(browser)
            page = await context.new_page()

            results = await self._do_search(page, image_path, image_url)

            await context.close()
            await browser.close()
            await playwright.stop()

            logger.info(f"[{self.engine_name}] Search complete: {len(results)} URLs")
            return {"urls": results, "engine": self.engine_name}

        except Exception as e:
            logger.error(f"[{self.engine_name}] Search failed: {e}")
            if playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass
            return {"urls": [], "error": str(e), "engine": self.engine_name}

    async def _launch_browser(self, playwright) -> Browser:
        """Launch Chromium with stealth and proxy config."""
        launch_args = {
            "headless": self.config.browser.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ]
        }

        if self.config.proxy.enabled and self.config.proxy.residential_url:
            launch_args["proxy"] = {"server": self.config.proxy.residential_url}

        browser = await playwright.chromium.launch(**launch_args)
        return browser

    async def _create_context(self, browser: Browser) -> BrowserContext:
        """Create browser context with evasion settings."""
        import random

        user_agent = random.choice(self._user_agents)

        context = await browser.new_context(
            user_agent=user_agent,
            viewport={
                "width": self.config.browser.viewport["width"],
                "height": self.config.browser.viewport["height"],
            },
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Stealth scripts
        if self.config.browser.stealth_mode:
            await context.add_init_script("""
                // Override navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                // Override chrome object
                window.chrome = { runtime: {} };
                // Override plugins
                Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                // Override language
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)

        return context

    def _normalize_url(self, url: str) -> str:
        """Clean and normalize a URL."""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            return ""
        # Remove tracking params
        for param in ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "fbclid", "gclid"]:
            url = self._strip_param(url, param)
        return url

    def _strip_param(self, url: str, param: str) -> str:
        """Remove a query parameter from a URL."""
        if f"{param}=" not in url:
            return url
        import re
        pattern = rf'[?&]{param}=[^&]*'
        url = re.sub(pattern, '', url)
        url = url.replace("?&", "?")
        if url.endswith("?"):
            url = url[:-1]
        return url

    @abstractmethod
    async def _do_search(self, page: Page, image_path: str, image_url: Optional[str] = None) -> List[Dict[str, str]]:
        """Engine-specific search implementation. Returns list of {url, title, snippet}."""
        ...
