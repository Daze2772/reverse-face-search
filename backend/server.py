"""Emergent backend shim — exposes the Reverse Face Search FastAPI app.

Supervisor expects ``server:app`` to be importable from ``/app/backend``.
This file wires up the original app (defined under ``/app/src``) so we don't
have to fork the codebase.
"""

import logging
import sys
from pathlib import Path

# Make the original project importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config           # noqa: E402
from src.main import setup_logging           # noqa: E402
from src.api.routes import create_app        # noqa: E402

_config = load_config()
setup_logging(_config)

logger = logging.getLogger("backend-shim")
logger.info("Booting Reverse Face Search backend behind /api/* ingress")

app = create_app()
