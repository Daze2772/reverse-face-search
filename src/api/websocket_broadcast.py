"""WebSocket broadcast — shared between API routes and search manager."""

import json
import logging
from typing import List

logger = logging.getLogger("ws")

active_ws_clients: List = []  # List of (websocket, search_id) tuples


async def broadcast_progress(search_id: str, data: dict):
    """Push progress update to all WebSocket clients watching this search."""
    payload = json.dumps(data)
    for ws, sid in active_ws_clients:
        if sid == search_id:
            try:
                await ws.send_text(payload)
            except Exception:
                pass
