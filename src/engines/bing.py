"""Bing Images reverse image search engine handler."""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.bing")


class BingEngine(BaseSearchEngine):
    """Reverse image search via Bing Images."""

    def __init__(self, config):
        super().__init__(config, "bing")

    async def _do_search(self, page: Page, image_path: str, image_url: Optional[str] = None) -> List[Dict[str, str]]:
        """Navigate to Bing Visual Search via URL-based image lookup."""
        results = []
        from urllib.parse import quote

        if image_url:
            encoded_url = quote(image_url, safe='')
        else:
            encoded_url = quote("https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg", safe='')
        
        bing_url = f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{encoded_url}"
        logger.info(f"[bing] Searching: {bing_url[:120]}...")
        
        await page.goto(bing_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Wait for results
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                link_count = await page.locator('a[href^="http"]').count()
                if link_count > 10:
                    break
            except Exception:
                pass

        await asyncio.sleep(2)
        results = await self._extract_results(page)
        return results

    async def _extract_results(self, page: Page) -> List[Dict[str, str]]:
        """Extract URLs from Bing visual search results."""
        results = []
        seen_urls = set()

        try:
            # Bing result selectors
            selectors = [
                'a[href^="http"]:not([href*="bing.com"]):not([href*="microsoft.com"])',
                '.richImageScrollContainer a[href^="http"]',
                '.imgpt a[href^="http"]',
                '.iusc a[href^="http"]',
                '.mmComponent_images a[href^="http"]',
                '.dgControl_list a[href^="http"]',
            ]

            for selector in selectors:
                try:
                    links = page.locator(selector)
                    count = await links.count()
                    for i in range(min(count, 50)):
                        try:
                            href = await links.nth(i).get_attribute("href")
                            if href and href.startswith("http") and "bing" not in href and "microsoft" not in href:
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
            logger.error(f"[bing] Result extraction error: {e}")

        # Fallback
        if len(results) == 0:
            try:
                raw = await page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href^="http"]');
                    return Array.from(links)
                        .filter(a => !a.href.includes('bing') && !a.href.includes('microsoft'))
                        .map(a => ({url: a.href, title: a.textContent.trim().substring(0, 200)}));
                }""")
                for link in raw:
                    url = self._normalize_url(link["url"])
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        results.append({"url": url, "title": link["title"], "snippet": ""})
            except Exception as e:
                logger.error(f"[bing] Fallback extraction error: {e}")

        logger.info(f"[bing] Extracted {len(results)} results")
        return results[:50]

    async def _detect_captcha(self, page: Page) -> bool:
        """Check for Bing CAPTCHA."""
        captcha_indicators = [
            'iframe[src*="captcha"]',
            '.g-recaptcha',
            '#captchaDialog',
        ]
        for indicator in captcha_indicators:
            if await page.locator(indicator).count() > 0:
                return True
        try:
            text = await page.inner_text("body")
            if "captcha" in text.lower() or "verify you're not a robot" in text.lower():
                return True
        except Exception:
            pass
        return False

    async def _handle_captcha(self, page: Page) -> bool:
        """Solve Bing CAPTCHA via 2Captcha."""
        api_key = self.config.captcha.api_key
        if not api_key:
            logger.warning("[bing] No CAPTCHA API key configured")
            return False

        try:
            from twocaptcha import TwoCaptcha
            solver = TwoCaptcha(api_key)
            site_key = await page.evaluate("""() => {
                const el = document.querySelector('[data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            }""")

            if site_key:
                result = solver.recaptcha(sitekey=site_key, url=page.url)
                token = result["code"]
                await page.evaluate(f"""
                    document.getElementById('g-recaptcha-response').innerHTML = '{token}';
                """)
                await asyncio.sleep(3)
                return True

        except Exception as e:
            logger.error(f"[bing] CAPTCHA solve failed: {e}")

        return False
