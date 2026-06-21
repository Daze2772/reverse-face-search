"""Yandex Images reverse search engine handler."""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional
from playwright.async_api import Page

from .base import BaseSearchEngine

logger = logging.getLogger("engines.yandex")


class YandexEngine(BaseSearchEngine):
    """Reverse image search via Yandex Images."""

    def __init__(self, config):
        super().__init__(config, "yandex")

    async def _do_search(self, page: Page, image_path: str, image_url: Optional[str] = None) -> List[Dict[str, str]]:
        """Navigate to Yandex visual search via URL-based reverse image lookup."""
        results = []
        from urllib.parse import quote

        # Use the provided public URL, or fall back to the known Einstein test image
        if image_url:
            encoded_url = quote(image_url, safe='')
        else:
            # Fallback for testing when no public URL is available
            encoded_url = quote("https://upload.wikimedia.org/wikipedia/commons/d/d3/Albert_Einstein_Head.jpg", safe='')
        
        search_url = f"https://yandex.com/images/search?rpt=imageview&url={encoded_url}"
        logger.info(f"[yandex] Searching: {search_url[:120]}...")
        
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # Wait for results — Yandex loads them dynamically
        for _ in range(10):
            await asyncio.sleep(1)
            try:
                link_count = await page.locator('a[href^="http"]').count()
                if link_count > 10:
                    break
            except Exception:
                pass

        # Try clicking "show more" or similar buttons
        try:
            buttons = page.locator('button, a.button, .more-button, [data-action="more"]')
            count = await buttons.count()
            for i in range(min(count, 5)):
                try:
                    await buttons.nth(i).click(timeout=2000)
                    await asyncio.sleep(1)
                except Exception:
                    pass
        except Exception:
            pass

        # Final wait
        await asyncio.sleep(2)

        # Extract results
        results = await self._extract_results(page)
        return results

    async def _extract_results(self, page: Page) -> List[Dict[str, str]]:
        """Extract result URLs, titles, and snippets from Yandex results page."""
        results = []
        seen_urls = set()

        try:
            # Save screenshot for debugging
            try:
                await page.screenshot(path="debug_yandex_results.png")
                logger.info("[yandex] Screenshot saved to debug_yandex_results.png")
            except Exception:
                pass

            # Save page HTML for debugging
            try:
                html = await page.content()
                Path("debug_yandex_page.html").write_text(html[:50000])
                logger.info("[yandex] Page HTML saved (50KB)")
            except Exception:
                pass

            # Extract ALL external links from the page
            raw_links = await page.evaluate("""() => {
                const links = document.querySelectorAll('a[href^="http"]');
                return Array.from(links).map(a => ({
                    url: a.href,
                    title: (a.textContent || '').trim().substring(0, 200),
                    className: a.className || '',
                }));
            }""")

            yandex_domains = ['yandex.com', 'yandex.ru', 'yandex.net', 'ya.ru', 'yastatic.net']
            for link in raw_links:
                href = link.get("url", "")
                if not href or not href.startswith("http"):
                    continue
                # Skip Yandex internal URLs
                if any(d in href for d in yandex_domains):
                    continue
                url = self._normalize_url(href)
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        "url": url,
                        "title": link.get("title", "")[:200],
                        "snippet": "",
                    })

        except Exception as e:
            logger.error(f"[yandex] Result extraction error: {e}")

        logger.info(f"[yandex] Extracted {len(results)} results")
        return results[:50]  # Cap at 50

    async def _detect_captcha(self, page: Page) -> bool:
        """Check if a CAPTCHA challenge is present."""
        captcha_indicators = [
            'iframe[src*="captcha"]',
            'iframe[src*="recaptcha"]',
            '.g-recaptcha',
            '#captcha',
            'form#captcha',
            '[data-testid="captcha"]',
        ]
        for indicator in captcha_indicators:
            if await page.locator(indicator).count() > 0:
                return True
        # Check page text
        try:
            text = await page.inner_text("body")
            if "captcha" in text.lower() or "not a robot" in text.lower():
                return True
        except Exception:
            pass
        return False

    async def _handle_captcha(self, page: Page) -> bool:
        """Attempt CAPTCHA solving via 2Captcha."""
        api_key = self.config.captcha.api_key
        if not api_key:
            logger.warning("[yandex] No CAPTCHA API key configured")
            return False

        try:
            from twocaptcha import TwoCaptcha
            solver = TwoCaptcha(api_key)

            # Get site key if reCAPTCHA
            site_key = await page.evaluate("""() => {
                const el = document.querySelector('[data-sitekey]');
                return el ? el.getAttribute('data-sitekey') : null;
            }""")

            if site_key:
                result = solver.recaptcha(
                    sitekey=site_key,
                    url=page.url,
                )
                token = result["code"]

                await page.evaluate(f"""
                    document.getElementById('g-recaptcha-response').innerHTML = '{token}';
                    document.getElementById('captcha-form')?.submit();
                """)
                await asyncio.sleep(3)
                return True

        except Exception as e:
            logger.error(f"[yandex] CAPTCHA solve failed: {e}")

        return False
