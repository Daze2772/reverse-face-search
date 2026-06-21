"""Main entry point — launch the Reverse Face Search server."""

import logging
import sys
from pathlib import Path

# Ensure the project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config            # noqa: E402
from src.api.routes import create_app         # noqa: E402


def setup_logging(config):
    """Configure structured logging to file and stdout."""
    log_config = config.logging
    log_dir = Path(log_config.file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_config.level.upper(), logging.INFO),
        format=log_config.format,
        handlers=[
            logging.FileHandler(log_config.file),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def main():
    config = load_config()
    setup_logging(config)

    logger = logging.getLogger("main")
    logger.info("=== Reverse Face Search Tool ===")
    logger.info(
        f"Engines: Yandex={'ON' if config.engines.yandex.enabled else 'OFF'}, "
        f"Google={'ON' if config.engines.google.enabled else 'OFF'}, "
        f"Bing={'ON' if config.engines.bing.enabled else 'OFF'}"
    )
    logger.info(
        f"Face embedding: {'ENABLED' if config.face.enabled else 'disabled'} "
        f"(threshold={config.face.similarity_threshold})"
    )

    app = create_app()

    import uvicorn
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level=config.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
