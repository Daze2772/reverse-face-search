"""FastAPI routes — image upload, search orchestration, results retrieval."""

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ..cache import TTLDiskCache
from ..config import AppConfig, load_config
from ..search_manager import SearchManager
from ..store import Store
from .websocket_broadcast import active_ws_clients, broadcast_progress

logger = logging.getLogger("api")


# ─── Background-task registry — prevent silent GC of fire-and-forget tasks ──
_background_tasks: set = set()


def _spawn_background(coro):
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ─── Lifespan ──────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise / tear down app-wide resources."""
    config: AppConfig = load_config()
    upload_dir = Path(config.upload.temp_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)
    Path(config.storage.dossier_dir).mkdir(parents=True, exist_ok=True)

    store = Store(config.storage.db_path)
    cache = TTLDiskCache(
        config.storage.cache_dir,
        ttl_seconds=config.intel.cache_ttl_hours * 3600,
    )
    manager = SearchManager(config, store=store, cache=cache)

    app.state.config = config
    app.state.store = store
    app.state.cache = cache
    app.state.search_manager = manager

    logger.info("Reverse Face Search v2 — services initialised")
    try:
        yield
    finally:
        store.close()
        logger.info("Shut down complete")


# ─── App factory ───────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    config: AppConfig = load_config()

    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI(title="Reverse Face Search", version="2.1.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    upload_rate = config.ratelimit.upload
    search_rate = config.ratelimit.search

    # ─── Dependency helpers ────────────────────────────────────────────────

    def get_manager(request: Request) -> SearchManager:
        return request.app.state.search_manager

    def get_config(request: Request) -> AppConfig:
        return request.app.state.config

    # ─── Endpoints ─────────────────────────────────────────────────────────

    @app.get("/api/health")
    async def healthcheck():
        return {"status": "ok", "version": "2.1.0"}

    @app.post("/api/upload")
    @limiter.limit(upload_rate)
    async def upload_image(
        request: Request,
        file: UploadFile = File(...),
        config: AppConfig = Depends(get_config),
    ):
        """Accept image upload, validate, generate search ID."""
        if file.content_type not in config.upload.allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type '{file.content_type}' not allowed. "
                       f"Accepted: {config.upload.allowed_types}",
            )

        contents = await file.read()
        size_mb = len(contents) / (1024 * 1024)
        if size_mb > config.upload.max_size_mb:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {size_mb:.1f}MB "
                       f"(max {config.upload.max_size_mb}MB)",
            )

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
            "status": "uploaded",
        }

    @app.post("/api/search/{search_id}")
    @limiter.limit(search_rate)
    async def start_search(
        request: Request,
        search_id: str,
        manager: SearchManager = Depends(get_manager),
        config: AppConfig = Depends(get_config),
    ):
        """Launch the full reverse search pipeline for an uploaded image."""
        temp_path = _find_temp_file(search_id, config.upload.temp_dir)
        if not temp_path:
            raise HTTPException(status_code=404, detail="Uploaded image not found. Upload first.")

        _spawn_background(manager.run_pipeline(search_id, str(temp_path)))
        return {"search_id": search_id, "status": "search_started"}

    @app.get("/api/dossier/{search_id}")
    async def get_dossier(search_id: str, manager: SearchManager = Depends(get_manager)):
        dossier = manager.get_dossier(search_id)
        if not dossier:
            raise HTTPException(status_code=404, detail="Dossier not found or search still in progress")
        return dossier

    @app.get("/api/report/{search_id}")
    async def get_report(
        search_id: str,
        config: AppConfig = Depends(get_config),
    ):
        pdf_path = Path(config.storage.dossier_dir) / f"{search_id}.pdf"
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF report not found.")
        return FileResponse(
            str(pdf_path),
            media_type="application/pdf",
            filename=f"intel-report-{search_id[:8]}.pdf",
        )

    @app.get("/api/status/{search_id}")
    async def get_status(search_id: str, manager: SearchManager = Depends(get_manager)):
        status = manager.get_status(search_id)
        if not status:
            raise HTTPException(status_code=404, detail="Search not found")
        return status

    @app.get("/api/recent")
    async def get_recent(
        limit: int = 25,
        manager: SearchManager = Depends(get_manager),
    ):
        """List recent searches (handy for the dashboard sidebar)."""
        return {"searches": manager.list_recent(min(limit, 100))}

    @app.websocket("/ws/{search_id}")
    async def websocket_progress(websocket: WebSocket, search_id: str):
        await websocket.accept()
        active_ws_clients.append((websocket, search_id))
        logger.info(f"WebSocket connected for search {search_id}")
        try:
            while True:
                # Treat any inbound payload as a heartbeat.
                await websocket.receive_text()
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for search {search_id}")
        finally:
            active_ws_clients[:] = [
                (ws, sid) for ws, sid in active_ws_clients if ws is not websocket
            ]

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        template_path = Path(__file__).resolve().parent.parent.parent / "templates" / "dashboard.html"
        if template_path.exists():
            return template_path.read_text()
        return "<h1>Dashboard template not found</h1>"

    @app.get("/api/config")
    async def get_public_config(config: AppConfig = Depends(get_config)):
        """Return sanitised config (no secrets)."""
        return {
            "engines": {
                "yandex": {"enabled": config.engines.yandex.enabled},
                "google": {"enabled": config.engines.google.enabled},
                "bing": {"enabled": config.engines.bing.enabled},
            },
            "upload": {
                "max_size_mb": config.upload.max_size_mb,
                "allowed_types": config.upload.allowed_types,
            },
            "features": {
                "face_embedding": config.face.enabled,
                "imgbb_configured": bool(os.environ.get("IMGBB_API_KEY")),
                "opensanctions_configured": bool(os.environ.get("OPENSANCTIONS_API_KEY")),
            },
        }

    return app


# ─── Helpers ───────────────────────────────────────────────────────────────


def _get_extension(filename: Optional[str], content_type: str) -> str:
    if filename and "." in filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".jpg", ".jpeg", ".png", ".webp"):
            return ext
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(content_type, ".jpg")


def _find_temp_file(search_id: str, upload_dir: str) -> Optional[Path]:
    """Look up a temp image file by search-id prefix."""
    d = Path(upload_dir)
    if not d.exists():
        return None
    # Use ``glob`` instead of iterating every file — faster on large dirs.
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        candidate = d / f"{search_id}{ext}"
        if candidate.exists():
            return candidate
    # Fallback: prefix match (legacy)
    for f in d.iterdir():
        if f.name.startswith(search_id):
            return f
    return None
