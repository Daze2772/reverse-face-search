"""
Standalone browser engine test — single Yandex search with Playwright.
Handles EPIPE gracefully and retries.
"""

import sys
import asyncio
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("browser_test")

TEST_IMAGE = PROJECT_ROOT / "uploads" / "einstein_test.jpg"


async def main():
    if not TEST_IMAGE.exists():
        logger.error("Test image not found. Run test_quick.py first.")
        return

    from src.config import load_config
    from src.engines.yandex import YandexEngine

    config = load_config()
    
    for attempt in range(1, 4):
        logger.info(f"=== Yandex search attempt {attempt}/3 ===")
        try:
            engine = YandexEngine(config)
            result = await engine.search(str(TEST_IMAGE))
            
            urls = result.get("urls", [])
            error = result.get("error")
            
            logger.info(f"Yandex result: {len(urls)} URLs")
            if error:
                logger.warning(f"Yandex error: {error}")
            
            if len(urls) >= 3:
                logger.info(f"SUCCESS — {len(urls)} URLs on attempt {attempt}")
                # Print first 5 URLs
                for u in urls[:5]:
                    print(f"  {u.get('url', '')[:100]}")
                return True
            
            logger.warning(f"Only {len(urls)} URLs — retrying...")
            
        except Exception as e:
            logger.error(f"Yandex exception (attempt {attempt}): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    logger.error("All Yandex attempts failed")
    return False


if __name__ == "__main__":
    success = asyncio.run(main())
    print(f"\nBrowser test: {'PASS' if success else 'FAIL'}")
