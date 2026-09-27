"""Voca: vocabulary learning with spaced repetition."""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, url_for
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from app.config import get_config  # noqa: E402  (after .env is loaded)
from app.core.libsql_dialect import register as register_libsql  # noqa: E402

register_libsql()

API_PREFIX = "/api/v1"


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True, static_folder=None)
    app.config.from_object(get_config(config_name))
    if overrides:
        app.config.update(overrides)

    _configure_database(app)
    if app.config["APP_ENV"] == "production":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    from app.core.errors import register_error_handlers
    from app.core.logging import configure_logging
    from app.extensions import db, jwt, limiter, migrate

    configure_logging(app)
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    jwt.init_app(app)
    limiter.init_app(app)

    from app import models  # noqa: F401  (register tables)
    from app.modules.auth.jwt_setup import init_jwt

    init_jwt(jwt)
    register_error_handlers(app)
    _register_blueprints(app)

    from app.cli import register_cli

    register_cli(app)

    @app.get("/healthz")
    def healthz():
        from sqlalchemy import text

        db.session.execute(text("select 1"))
        return {"status": "ok"}

    @app.get("/favicon.ico")
    def favicon():
        return redirect(url_for("web.static", filename="favicon.svg"))

    return app


def _configure_database(app: Flask) -> None:
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        if app.config["APP_ENV"] == "production":
            raise RuntimeError("Production requires TURSO_DATABASE_URL (+ TURSO_AUTH_TOKEN) or DATABASE_URL")
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{Path(app.instance_path) / 'voca.db'}"


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """Enforce foreign keys on SQLite / libSQL connections."""
    module = type(dbapi_connection).__module__
    if "sqlite" in module or "libsql" in module:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception:  # remote libSQL may not accept per-connection pragmas
            pass
        finally:
            cursor.close()


def _register_blueprints(app: Flask) -> None:
    from app.modules.auth.routes import bp as auth_bp
    from app.modules.collections.routes import bp as collections_bp
    from app.modules.external.routes import gateway, manage
    from app.modules.learning.routes import bp as learning_bp
    from app.modules.stats.routes import bp as stats_bp
    from app.modules.vocabulary.routes import bp as vocabulary_bp
    from app.web import bp as web_bp

    for blueprint in (auth_bp, vocabulary_bp, collections_bp, learning_bp, stats_bp, gateway, manage):
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)
    app.register_blueprint(web_bp)
