"""Base engine class for reverse image search.

The previous implementation re-launched a Playwright process per engine, per
search. This rewrite supports an external :class:`BrowserPool` (passed in by
:mod:`src.search_manager`) so the three engines share a single browser per
search instead of spawning three Chromium processes.
"""

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
)

logger = logging.getLogger("engines")


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

STEALTH_INIT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
"""


class BaseSearchEngine(ABC):
    """Abstract base for reverse image search engine handlers."""

    # Domains that belong to *this* engine — filtered out of extracted links.
    OWN_DOMAINS: List[str] = []

    # Hard cap on results to return.
    MAX_RESULTS: int = 50

    def __init__(self, config, engine_name: str):
        self.config = config
        self.engine_name = engine_name
        self.OWN_DOMAINS = list(self.OWN_DOMAINS)  # per-instance copy

    async def search(
        self,
        image_path: str,
        image_url: Optional[str] = None,
        browser: Optional[Browser] = None,
    ) -> Dict[str, Any]:
        """Public entry point.

        If ``image_url`` is missing we **do not silently substitute Einstein**
        anymore — we return an explicit error so the caller knows the file-host
        upload failed.
        """
        logger.info(f"[{self.engine_name}] Starting reverse image search")

        if not image_url:
            msg = "no public image_url available — file host upload failed"
            logger.warning(f"[{self.engine_name}] {msg}")
            return {"urls": [], "error": msg, "engine": self.engine_name}

        playwright = None
        owns_browser = browser is None
        local_browser: Optional[Browser] = browser
        try:
            if owns_browser:
                playwright = await async_playwright().start()
                local_browser = await self._launch_browser(playwright)

            context = await self._create_context(local_browser)
            page = await context.new_page()

            try:
                results = await self._do_search(page, image_path, image_url)
            finally:
                await context.close()

            logger.info(f"[{self.engine_name}] Search complete: {len(results)} URLs")
            return {"urls": results, "engine": self.engine_name}

        except Exception as e:
            logger.error(f"[{self.engine_name}] Search failed: {e}")
            return {"urls": [], "error": str(e), "engine": self.engine_name}

        finally:
            if owns_browser and local_browser:
                try:
                    await local_browser.close()
                except Exception:
                    pass
            if owns_browser and playwright:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    async def _launch_browser(self, playwright) -> Browser:
        """Launch Chromium with stealth and proxy config."""
        launch_args = {
            "headless": self.config.browser.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # NOTE: deliberately removed --disable-web-security (security hole)
            ],
        }

        proxy_url = self.config.proxy.residential_url
        if self.config.proxy.enabled and proxy_url:
            launch_args["proxy"] = {"server": proxy_url}

        return await playwright.chromium.launch(**launch_args)

    async def _create_context(self, browser: Browser) -> BrowserContext:
        """Create a stealth context per search."""
        ua = random.choice(USER_AGENTS) if self.config.browser.user_agent_rotation else USER_AGENTS[0]

        context = await browser.new_context(
            user_agent=ua,
            viewport={
                "width": self.config.browser.viewport["width"],
                "height": self.config.browser.viewport["height"],
            },
            locale="en-US",
            timezone_id="America/New_York",
        )

        if self.config.browser.stealth_mode:
            await context.add_init_script(STEALTH_INIT_SCRIPT)

        return context

    # ─── Shared extraction ─────────────────────────────────────────────────

    async def extract_external_links(
        self,
        page: Page,
        own_domains: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """Extract every external ``<a href>`` from the page in one JS call.

        This replaces the per-engine ``_extract_results`` copy-paste.
        """
        own = list(own_domains or self.OWN_DOMAINS)
        try:
            raw = await page.evaluate(
                """(own) => {
                    const links = document.querySelectorAll('a[href^="http"]');
                    const out = [];
                    for (const a of links) {
                        const h = a.href;
                        if (!h) continue;
                        let skip = false;
                        for (const d of own) {
                            if (h.includes(d)) { skip = true; break; }
                        }
                        if (skip) continue;
                        out.push({
                            url: h,
                            title: (a.textContent || '').trim().substring(0, 200),
                        });
                    }
                    return out;
                }""",
                own,
            )
        except Exception as e:
            logger.error(f"[{self.engine_name}] Link extraction error: {e}")
            return []

        results: List[Dict[str, str]] = []
        seen = set()
        for link in raw:
            normalized = self._normalize_url(link.get("url", ""))
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            results.append({
                "url": normalized,
                "title": (link.get("title") or "")[:200],
                "snippet": "",
            })
            if len(results) >= self.MAX_RESULTS:
                break
        return results

    async def wait_for_results(self, page: Page, min_links: int = 10, attempts: int = 10) -> None:
        """Poll the page until we see a reasonable number of links, or timeout."""
        for _ in range(attempts):
            await asyncio.sleep(1)
            try:
                if await page.locator('a[href^="http"]').count() > min_links:
                    return
            except Exception:
                pass

    # ─── URL hygiene ───────────────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        """Clean and normalise a URL: strip whitespace, fix protocol-relative, drop trackers."""
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        if not url.startswith("http"):
            return ""
        for param in ("utm_source", "utm_medium", "utm_campaign", "utm_content",
                      "utm_term", "fbclid", "gclid", "mc_eid", "mc_cid"):
            url = self._strip_param(url, param)
        return url

    @staticmethod
    def _strip_param(url: str, param: str) -> str:
        import re
        if f"{param}=" not in url:
            return url
        url = re.sub(rf'[?&]{param}=[^&]*', "", url).replace("?&", "?")
        return url[:-1] if url.endswith("?") else url

    @abstractmethod
    async def _do_search(
        self,
        page: Page,
        image_path: str,
        image_url: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Engine-specific search. Returns ``[{url, title, snippet}, ...]``."""
        raise NotImplementedError
