"""Configuration loader — reads config.yaml into typed dataclasses."""

import yaml
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


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


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load and parse config.yaml into AppConfig."""
    path = path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

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

    return app
