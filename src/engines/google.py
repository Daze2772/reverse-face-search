"""Google Lens reverse image search engine handler."""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.google")


class GoogleEngine(BaseSearchEngine):
    """Reverse image search via Google Lens."""

    def __init__(self, config):
        super().__init__(config, "google")

    async def _do_search(self, page: Page, image_path: str, image_url: Optional[str] = None) -> List[Dict[str, str]]:
        """Navigate to Google Lens via URL-based image lookup."""
        results = []
        from urllib.parse import quote

        if image_url:
            encoded_url = quote(image_url, safe='')
        else:
            encoded_url = quote("https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg", safe='')
        
        lens_url = f"https://lens.google.com/uploadbyurl?url={encoded_url}"
        logger.info(f"[google] Searching: {lens_url[:120]}...")
        
        await page.goto(lens_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Handle cookie consent
        try:
            for text in ["Accept all", "I agree", "Accept", "Alle akzeptieren"]:
                btn = page.locator(f'button:has-text("{text}")').first
                if await btn.count() > 0:
                    await btn.click(timeout=3000)
                    await asyncio.sleep(1)
                    break
        except Exception:
            pass

        # Wait for Lens results
        await asyncio.sleep(5)
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                link_count = await page.locator('a[href^="http"]').count()
                if link_count > 10:
                    break
            except Exception:
                pass

        # Save debug
        try:
            await page.screenshot(path="debug_google_results.png")
            html = await page.content()
            Path("debug_google_page.html").write_text(html[:50000])
        except Exception:
            pass

        results = await self._extract_results(page)
        return results

    async def _extract_results(self, page: Page) -> List[Dict[str, str]]:
        """Extract URLs from Google Lens results page."""
        results = []
        seen_urls = set()

        try:
            # Google Lens results — visual matches section
            # Try multiple selectors for result cards
            selectors = [
                'a[href^="http"]:not([href*="google.com"])',
                '[data-result] a[href^="http"]',
                '.match-card a[href^="http"]',
                '.UAiK1e a[href^="http"]',
                'a[data-ved]',
            ]

            for selector in selectors:
                try:
                    links = page.locator(selector)
                    count = await links.count()
                    for i in range(min(count, 50)):
                        try:
                            href = await links.nth(i).get_attribute("href")
                            if href and href.startswith("http") and "google" not in href:
                                if href not in seen_urls:
                                    seen_urls.add(href)
                                    url = self._normalize_url(href)
                                    if url:
                                        title = ""
                                        try:
                                            title = await links.nth(i).inner_text()
                                        except Exception:
                                            pass
                                        results.append({"url": url, "title": title[:200] if title else "", "snippet": ""})
                        except Exception:
                            continue
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"[google] Result extraction error: {e}")

        # Fallback: JS extraction
        if len(results) == 0:
            try:
                raw = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href^="http"]');
                    return Array.from(links)
                        .filter(a => !a.href.includes('google'))
                        .map(a => ({url: a.href, title: a.textContent.trim().substring(0, 200)}));
                }""")
                for link in raw:
                    url = self._normalize_url(link["url"])
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append({"url": url, "title": link["title"], "snippet": ""})
            except Exception as e:
                logger.error(f"[google] Fallback extraction error: {e}")

        logger.info(f"[google] Extracted {len(results)} results")
        return results[:50]

    async def _detect_captcha(self, page: Page) -> bool:
        """Check for Google CAPTCHA."""
        captcha_indicators = [
            'iframe[src*="recaptcha"]',
            '.g-recaptcha',
            '#recaptcha',
            'form[action*="captcha"]',
        ]
        for indicator in captcha_indicators:
            if await page.locator(indicator).count() > 0:
                return True
        try:
            text = await page.inner_text("body")
            if "unusual traffic" in text.lower() or "not a robot" in text.lower():
                return True
        except Exception:
            pass
        return False

    async def _handle_captcha(self, page: Page) -> bool:
        """Solve Google CAPTCHA via 2Captcha."""
        api_key = self.config.captcha.api_key
        if not api_key:
            logger.warning("[google] No CAPTCHA API key configured")
            return False

        try:
            from twocaptcha import TwoCaptcha
            solver = TwoCaptcha(api_key)

            site_key = await page.evaluate("""() => {
                const el = document.querySelector('[data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            }""")

            if not site_key:
                site_key = self.config.captcha.site_key_google

            if site_key:
                result = solver.recaptcha(sitekey=site_key, url=page.url)
                token = result["code"]
                await page.evaluate(f"""
                    document.getElementById('g-recaptcha-response').innerHTML = '{token}';
                """)
                await page.evaluate("document.querySelector('form')?.submit()")
                await asyncio.sleep(5)
                return True

        except Exception as e:
            logger.error(f"[google] CAPTCHA solve failed: {e}")

        return False
