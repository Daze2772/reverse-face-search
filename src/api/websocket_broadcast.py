"""WebSocket broadcast — shared between API routes and search manager."""

import asyncio
import json
import logging
from typing import List, Tuple, Any

logger = logging.getLogger("ws")

# List of (websocket, search_id) tuples. Replaced at app startup so that
# tests can clean state; using a mutable global keeps the previous import
# semantics intact.
active_ws_clients: List[Tuple[Any, str]] = []


async def broadcast_progress(search_id: str, data: dict) -> None:
    """Push progress update to all WebSocket clients watching this search."""
    payload = json.dumps(data, default=str)
    dead: List[Tuple[Any, str]] = []

    for ws, sid in list(active_ws_clients):
        if sid != search_id:
            continue
        try:
            await ws.send_text(payload)
        except Exception as e:
            logger.debug(f"WS send failed for {sid}: {e}")
            dead.append((ws, sid))

    for entry in dead:
        try:
            active_ws_clients.remove(entry)
        except ValueError:
            pass
