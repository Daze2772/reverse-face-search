"""
Multi-engine reverse search test — all three engines in parallel.
"""

import sys
import asyncio
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("multi_engine_test")

TEST_IMAGE = PROJECT_ROOT / "uploads" / "einstein_test.jpg"


async def main():
    from src.config import load_config
    from src.engines.yandex import YandexEngine
    from src.engines.google import GoogleEngine
    from src.engines.bing import BingEngine

    config = load_config()

    async def run_engine(name, engine):
        try:
            result = await engine.search(str(TEST_IMAGE))
            count = len(result.get("urls", []))
            error = result.get("error")
            logger.info(f"{name}: {count} URLs" + (f" (error: {error})" if error else ""))
            return name, count, error
        except Exception as e:
            logger.error(f"{name}: {e}")
            return name, 0, str(e)

    engines = {
        "yandex": YandexEngine(config),
    }
    if config.engines.google.enabled:
        engines["google"] = GoogleEngine(config)
    if config.engines.bing.enabled:
        engines["bing"] = BingEngine(config)

    tasks = [run_engine(name, eng) for name, eng in engines.items()]
    results = await asyncio.gather(*tasks)

    working = sum(1 for _, count, _ in results if count > 0)
    logger.info(f"Working engines: {working}/{len(engines)}")
    
    for name, count, error in results:
        status = "✅" if count > 0 else "❌"
        logger.info(f"  {status} {name}: {count} URLs")
        if error:
            logger.info(f"       error: {error}")

    print(f"\nMulti-engine test: {working}/{len(engines)} engines returned results")


if __name__ == "__main__":
    asyncio.run(main())
