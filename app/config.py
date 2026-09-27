"""Environment-driven configuration. Nothing secret is hardcoded for production."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from sqlalchemy.pool import NullPool

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _turso_uri(url: str) -> str:
    """libsql://db-org.turso.io -> sqlite+libsql://db-org.turso.io?secure=true"""
    for prefix, secure in (("libsql://", True), ("https://", True), ("wss://", True), ("http://", False), ("ws://", False)):
        if url.startswith(prefix):
            host = url[len(prefix):].rstrip("/")
            return f"sqlite+libsql://{host}?secure={'true' if secure else 'false'}"
    raise ValueError(f"Unsupported TURSO_DATABASE_URL: {url!r}")


def database_settings() -> tuple[str | None, dict]:
    """Returns (SQLAlchemy URI, engine options)."""
    explicit = _env("DATABASE_URL")
    turso_url = _env("TURSO_DATABASE_URL")
    if explicit:
        uri = explicit
    elif turso_url:
        uri = _turso_uri(turso_url)
    else:
        return None, {}

    options: dict = {}
    if uri.startswith("sqlite+libsql://"):
        # Serverless: Hrana streams expire when idle, so never keep pooled connections.
        options["poolclass"] = NullPool
        token = _env("TURSO_AUTH_TOKEN")
        if token:
            options["connect_args"] = {"auth_token": token}
    return uri, options


class Config:
    APP_ENV = "development"
    DEBUG = False
    TESTING = False

    SECRET_KEY = _env("SECRET_KEY", "dev-secret-key-not-for-production")
    JWT_SECRET_KEY = _env("JWT_SECRET_KEY", "dev-jwt-secret-key-not-for-production-32b")

    SQLALCHEMY_DATABASE_URI, SQLALCHEMY_ENGINE_OPTIONS = database_settings()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # JWT: header (mobile/API) or httpOnly cookies (web) with double-submit CSRF.
    JWT_TOKEN_LOCATION = ["headers", "cookies"]
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    JWT_COOKIE_SECURE = False
    JWT_COOKIE_SAMESITE = "Lax"
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_SESSION_COOKIE = False
    REFRESH_REUSE_GRACE_SECONDS = 30

    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = _env("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    LOG_LEVEL = _env("LOG_LEVEL", "INFO")
    DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
    SEND_FILE_MAX_AGE_DEFAULT = timedelta(hours=12)
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024


class DevelopmentConfig(Config):
    APP_ENV = "development"
    DEBUG = True


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
    RATELIMIT_ENABLED = False
    SECRET_KEY = "test-secret"
    JWT_SECRET_KEY = "test-jwt-secret-key-with-at-least-32-bytes"
    LOG_LEVEL = "WARNING"


class ProductionConfig(Config):
    APP_ENV = "production"
    JWT_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    name = name or _env("APP_ENV") or ("production" if _env("VERCEL") else "development")
    return CONFIGS.get(name, DevelopmentConfig)
