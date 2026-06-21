"""FastAPI routes — image upload, search orchestration, results retrieval."""

import os
import uuid
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import load_config, AppConfig
from ..search_manager import SearchManager
from .websocket_broadcast import active_ws_clients, broadcast_progress

logger = logging.getLogger("api")

config: AppConfig = load_config()
search_manager: Optional[SearchManager] = None


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    global search_manager

    app = FastAPI(title="Reverse Face Search", version="1.0.0")
    search_manager = SearchManager(config)

    # Ensure upload directory exists
    upload_dir = Path(config.upload.temp_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Ensure logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Mount static files
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # === Upload endpoint (Stage 1) ===
    @app.post("/api/upload")
    async def upload_image(file: UploadFile = File(...)):
        """Accept image upload, validate, generate search ID."""
        # Validate MIME type
        if file.content_type not in config.upload.allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type '{file.content_type}' not allowed. Accepted: {config.upload.allowed_types}"
            )

        # Validate file size
        contents = await file.read()
        size_mb = len(contents) / (1024 * 1024)
        if size_mb > config.upload.max_size_mb:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {size_mb:.1f}MB (max {config.upload.max_size_mb}MB)"
            )

        # Generate search ID and save temp file
        search_id = str(uuid.uuid4())
        ext = _get_extension(file.filename, file.content_type)
        temp_path = Path(config.upload.temp_dir) / f"{search_id}{ext}"

        with open(temp_path, "wb") as f:
            f.write(contents)

        logger.info(f"Image uploaded: {search_id} ({size_mb:.1f}MB, {file.content_type})")

        return {
            "search_id": search_id,
            "filename": file.filename,
            "size_mb": round(size_mb, 2),
            "content_type": file.content_type,
            "status": "uploaded"
        }

    # === Search endpoint (Stage 2-6) ===
    @app.post("/api/search/{search_id}")
    async def start_search(search_id: str):
        """Launch the full reverse search pipeline for an uploaded image."""
        if not search_manager:
            raise HTTPException(status_code=500, detail="Search manager not initialized")

        temp_path = _find_temp_file(search_id)
        if not temp_path:
            raise HTTPException(status_code=404, detail="Uploaded image not found. Upload first.")

        # Run search asynchronously
        asyncio.create_task(search_manager.run_pipeline(search_id, str(temp_path)))

        return {
            "search_id": search_id,
            "status": "search_started"
        }

    # === Dossier retrieval ===
    @app.get("/api/dossier/{search_id}")
    async def get_dossier(search_id: str):
        """Retrieve the assembled dossier for a completed search."""
        if not search_manager:
            raise HTTPException(status_code=500, detail="Search manager not initialized")

        dossier = search_manager.get_dossier(search_id)
        if not dossier:
            raise HTTPException(status_code=404, detail="Dossier not found or search still in progress")

        return dossier

    # === PDF Report download ===
    @app.get("/api/report/{search_id}")
    async def get_report(search_id: str):
        """Download the PDF intelligence report."""
        if not search_manager:
            raise HTTPException(status_code=500, detail="Search manager not initialized")

        pdf_path = Path("dossiers") / f"{search_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF report not found. Search may still be running.")

        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=f"intel-report-{search_id[:8]}.pdf"
        )

    # === Search status ===
    @app.get("/api/status/{search_id}")
    async def get_status(search_id: str):
        """Get live status of a search."""
        if not search_manager:
            raise HTTPException(status_code=500, detail="Search manager not initialized")

        status = search_manager.get_status(search_id)
        if not status:
            raise HTTPException(status_code=404, detail="Search not found")

        return status

    # === WebSocket for live progress ===
    @app.websocket("/ws/{search_id}")
    async def websocket_progress(websocket: WebSocket, search_id: str):
        await websocket.accept()
        active_ws_clients.append((websocket, search_id))
        logger.info(f"WebSocket connected for search {search_id}")

        try:
            while True:
                data = await websocket.receive_text()
                # Client heartbeat, no-op
        except WebSocketDisconnect:
            active_ws_clients[:] = [
                (ws, sid) for ws, sid in active_ws_clients if ws != websocket
            ]
            logger.info(f"WebSocket disconnected for search {search_id}")

    # === Dashboard ===
    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Serve the dashboard HTML."""
        template_path = Path(__file__).resolve().parent.parent.parent / "templates" / "dashboard.html"
        if template_path.exists():
            return template_path.read_text()
        return "<h1>Dashboard template not found</h1>"

    # === Config endpoint ===
    @app.get("/api/config")
    async def get_config():
        """Return sanitized config (no secrets)."""
        return {
            "engines": {
                "yandex": {"enabled": config.engines.yandex.enabled},
                "google": {"enabled": config.engines.google.enabled},
                "bing": {"enabled": config.engines.bing.enabled},
            },
            "upload": {
                "max_size_mb": config.upload.max_size_mb,
                "allowed_types": config.upload.allowed_types,
            }
        }

    return app


def _get_extension(filename: Optional[str], content_type: str) -> str:
    """Map MIME types and filenames to file extensions."""
    if filename and "." in filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return ext
    mime_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return mime_map.get(content_type, ".jpg")


def _find_temp_file(search_id: str) -> Optional[Path]:
    """Find a temp image file by search ID prefix."""
    upload_dir = Path(config.upload.temp_dir)
    for f in upload_dir.iterdir():
        if f.name.startswith(search_id):
            return f
    return None



