"""Configuration loader.

Reads ``config.yaml`` and overlays environment variables (loaded from ``.env``
by ``python-dotenv``). Secrets always come from the environment, never from
the YAML file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

# Load .env into os.environ as early as possible.
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_PATH = PROJECT_ROOT / "config.yaml"


# ─── Dataclasses ───────────────────────────────────────────────────────────


@dataclass
class UploadConfig:
    max_size_mb: int = 20
    allowed_types: list = field(default_factory=lambda: ["image/jpeg", "image/png", "image/webp"])
    temp_dir: str = "uploads"
    auto_purge_after_search: bool = True


@dataclass
class CaptchaConfig:
    provider: str = "2captcha"
    api_key: str = ""
    site_key_google: str = ""
    max_retries: int = 3
    timeout_seconds: int = 120


@dataclass
class ProxyConfig:
    enabled: bool = False
    residential_url: str = ""
    rotation: str = "per_session"


@dataclass
class EngineConfig:
    enabled: bool = True
    base_url: str = ""
    timeout_seconds: int = 60


@dataclass
class EnginesConfig:
    yandex: EngineConfig = field(default_factory=EngineConfig)
    google: EngineConfig = field(default_factory=EngineConfig)
    bing: EngineConfig = field(default_factory=EngineConfig)


@dataclass
class BrowserConfig:
    headless: bool = True
    pool_size: int = 3
    stealth_mode: bool = True
    user_agent_rotation: bool = True
    viewport: dict = field(default_factory=lambda: {"width": 1920, "height": 1080})


@dataclass
class MaigretConfig:
    path: str = "maigret"
    timeout_per_username: int = 300
    max_sites: int = 500
    async_mode: bool = True


@dataclass
class ClusteringConfig:
    social_domains: dict = field(default_factory=dict)
    news_domains: list = field(default_factory=list)
    forum_domains: list = field(default_factory=list)
    blog_domains: list = field(default_factory=list)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/reverse_face_search.log"
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    ws_heartbeat_seconds: int = 30


@dataclass
class FaceConfig:
    """Optional InsightFace-based embedding verification."""
    enabled: bool = False
    similarity_threshold: float = 0.55
    model_name: str = "buffalo_l"
    max_images_per_engine: int = 10  # cap embedding work


@dataclass
class StorageConfig:
    db_path: str = "data/rfs.sqlite"
    dossier_dir: str = "dossiers"
    upload_dir: str = "uploads"
    cache_dir: str = "cache"


@dataclass
class RateLimitConfig:
    upload: str = "10/minute"
    search: str = "5/minute"


@dataclass
class IntelConfig:
    opensanctions_api_key: str = ""
    cache_ttl_hours: int = 24


@dataclass
class FileHostConfig:
    imgbb_api_key: str = ""


@dataclass
class AppConfig:
    upload: UploadConfig = field(default_factory=UploadConfig)
    captcha: CaptchaConfig = field(default_factory=CaptchaConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    engines: EnginesConfig = field(default_factory=EnginesConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    maigret: MaigretConfig = field(default_factory=MaigretConfig)
    clustering: ClusteringConfig = field(default_factory=ClusteringConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    ratelimit: RateLimitConfig = field(default_factory=RateLimitConfig)
    intel: IntelConfig = field(default_factory=IntelConfig)
    filehost: FileHostConfig = field(default_factory=FileHostConfig)
    cors_origins: List[str] = field(default_factory=lambda: ["*"])


# ─── Helpers ───────────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str, default: List[str]) -> List[str]:
    val = os.environ.get(name)
    if not val:
        return default
    return [v.strip() for v in val.split(",") if v.strip()]


# ─── Loader ────────────────────────────────────────────────────────────────


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load and parse config.yaml into AppConfig, then overlay environment vars."""
    path = path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    app = AppConfig()

    if "upload" in raw:
        app.upload = UploadConfig(**raw["upload"])
    if "captcha" in raw:
        app.captcha = CaptchaConfig(**raw["captcha"])
    if "proxy" in raw:
        app.proxy = ProxyConfig(**raw["proxy"])
    if "engines" in raw:
        eng = raw["engines"]
        app.engines.yandex = EngineConfig(**eng.get("yandex", {}))
        app.engines.google = EngineConfig(**eng.get("google", {}))
        app.engines.bing = EngineConfig(**eng.get("bing", {}))
    if "browser" in raw:
        app.browser = BrowserConfig(**raw["browser"])
    if "maigret" in raw:
        app.maigret = MaigretConfig(**raw["maigret"])
    if "clustering" in raw:
        app.clustering = ClusteringConfig(**raw["clustering"])
    if "logging" in raw:
        app.logging = LoggingConfig(**raw["logging"])
    if "server" in raw:
        app.server = ServerConfig(**raw["server"])

    # ─── Environment overrides ─────────────────────────────────────────────

    # Server
    app.server.host = os.environ.get("RFS_HOST", app.server.host)
    if os.environ.get("RFS_PORT"):
        app.server.port = int(os.environ["RFS_PORT"])
    app.logging.level = os.environ.get("RFS_LOG_LEVEL", app.logging.level)

    # Storage paths
    app.storage.db_path = os.environ.get("RFS_DB_PATH", app.storage.db_path)
    app.storage.dossier_dir = os.environ.get("RFS_DOSSIER_DIR", app.storage.dossier_dir)
    app.storage.upload_dir = os.environ.get("RFS_UPLOAD_DIR", app.upload.temp_dir)
    app.storage.cache_dir = os.environ.get("RFS_CACHE_DIR", app.storage.cache_dir)
    app.upload.temp_dir = app.storage.upload_dir  # keep them in sync

    # Engine enable list
    requested = _env_list("RFS_ENGINES", [])
    if requested:
        names = set(requested)
        app.engines.yandex.enabled = "yandex" in names
        app.engines.google.enabled = "google" in names
        app.engines.bing.enabled = "bing" in names

    # Proxy
    app.proxy.residential_url = os.environ.get("RFS_PROXY_URL", app.proxy.residential_url)
    if app.proxy.residential_url:
        app.proxy.enabled = True

    # Secrets — always from env
    app.captcha.api_key = os.environ.get("TWOCAPTCHA_API_KEY", app.captcha.api_key)
    app.intel.opensanctions_api_key = os.environ.get(
        "OPENSANCTIONS_API_KEY", app.intel.opensanctions_api_key
    )
    app.filehost.imgbb_api_key = os.environ.get("IMGBB_API_KEY", "")

    # Face embedding
    app.face.enabled = _env_bool("RFS_FACE_EMBEDDING_ENABLED", app.face.enabled)
    app.face.similarity_threshold = _env_float(
        "RFS_FACE_SIMILARITY_THRESHOLD", app.face.similarity_threshold
    )

    # Rate limits
    app.ratelimit.upload = os.environ.get("RFS_UPLOAD_RATE", app.ratelimit.upload)
    app.ratelimit.search = os.environ.get("RFS_SEARCH_RATE", app.ratelimit.search)

    # CORS
    app.cors_origins = _env_list("RFS_CORS_ORIGINS", app.cors_origins)

    return app
