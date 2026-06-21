"""Main entry point — launch the Reverse Face Search server."""

import sys
import logging
from pathlib import Path

# Ensure the project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.api.routes import create_app


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

    # Reduce noise from third-party libs
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def main():
    """Launch the web server."""
    config = load_config()
    setup_logging(config)

    logger = logging.getLogger("main")
    logger.info("=== Reverse Face Search Tool ===")
    logger.info(f"Engines: Yandex={'ON' if config.engines.yandex.enabled else 'OFF'}, "
                f"Google={'ON' if config.engines.google.enabled else 'OFF'}, "
                f"Bing={'ON' if config.engines.bing.enabled else 'OFF'}")

    app = create_app()

    import uvicorn
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
