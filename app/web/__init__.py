"""Server-rendered pages (Jinja + HTMX). Mutations go through the JSON API via static/js/api.js."""
from __future__ import annotations

from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, redirect, request, url_for
from flask_jwt_extended import decode_token, get_csrf_token, set_access_cookies, set_refresh_cookies, unset_jwt_cookies
from jwt.exceptions import PyJWTError

from app.core.errors import AppError
from app.extensions import db
from app.modules.auth import service as auth_service
from app.modules.auth.models import User

# Static files live in public/static: Vercel's CDN serves public/** directly in production,
# while Flask serves the same /static/... URLs locally.
STATIC_DIR = Path(__file__).resolve().parents[2] / "public" / "static"
bp = Blueprint("web", __name__, template_folder="templates", static_folder=str(STATIC_DIR), static_url_path="/static")


def _decode(token: str | None, expected_type: str) -> dict | None:
    if not token:
        return None
    try:
        claims = decode_token(token)
    except PyJWTError:
        return None
    return claims if claims.get("type") == expected_type else None


def load_web_user() -> User | None:
    """Access cookie first; if it expired, silently rotate using the refresh cookie."""
    cfg = current_app.config
    claims = _decode(request.cookies.get(cfg["JWT_ACCESS_COOKIE_NAME"]), "access")
    if claims:
        user = db.session.get(User, claims["sub"])
        if user is not None and user.is_active:
            return user

    refresh = _decode(request.cookies.get(cfg["JWT_REFRESH_COOKIE_NAME"]), "refresh")
    if refresh:
        try:
            pair = auth_service.rotate_refresh_token(refresh["jti"], request.headers.get("User-Agent"), request.remote_addr)
        except AppError:
            g.clear_auth_cookies = True
            return None
        g.pending_tokens = pair
        return pair.user
    if request.cookies.get(cfg["JWT_ACCESS_COOKIE_NAME"]) or request.cookies.get(cfg["JWT_REFRESH_COOKIE_NAME"]):
        g.clear_auth_cookies = True
    return None


@bp.before_app_request
def _load_user():
    g.user = None
    if request.blueprint == "web" and request.endpoint != "web.static":
        g.user = load_web_user()


@bp.after_app_request
def _write_auth_cookies(response):
    pair = g.pop("pending_tokens", None)
    if pair is not None:
        set_access_cookies(response, pair.access_token)
        set_refresh_cookies(response, pair.refresh_token)
    elif g.pop("clear_auth_cookies", False):
        unset_jwt_cookies(response)
    return response


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            if request.headers.get("HX-Request"):
                return "", 401, {"HX-Redirect": url_for("web.login")}
            return redirect(url_for("web.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapper


def safe_next(target: str | None) -> str:
    if target:
        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc and target.startswith("/") and not target.startswith("//"):
            return target
    return url_for("web.dashboard")


def form_csrf_token() -> str:
    """CSRF value for plain HTML forms, tied to the refresh cookie."""
    pair = g.get("pending_tokens")
    if pair is not None:
        return get_csrf_token(pair.refresh_token)
    return request.cookies.get(current_app.config["JWT_REFRESH_CSRF_COOKIE_NAME"], "")


@bp.app_context_processor
def _template_globals():
    return {"current_user": g.get("user"), "form_csrf_token": form_csrf_token}


from app.web import filters, routes  # noqa: E402,F401
