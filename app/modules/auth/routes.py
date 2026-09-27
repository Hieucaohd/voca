"""/api/v1/auth and /api/v1/me.

Web clients receive tokens as httpOnly cookies (set by the web login form);
API/mobile clients receive them in the JSON body and send ``Authorization: Bearer``.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, get_jwt, jwt_required, set_access_cookies, set_refresh_cookies, unset_jwt_cookies

from app.core.validation import parse_body
from app.extensions import limiter
from app.modules.auth import service
from app.modules.auth.schemas import LoginIn, PasswordChange, ProfileUpdate, RegisterIn, user_to_dict

bp = Blueprint("auth_api", __name__)


def _client() -> tuple[str | None, str | None]:
    return request.headers.get("User-Agent"), request.remote_addr


def _token_body(pair: service.TokenPair) -> dict:
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": "Bearer",
        "user": user_to_dict(pair.user),
    }


def _uses_bearer() -> bool:
    return request.headers.get("Authorization", "").startswith("Bearer ")


@bp.post("/auth/register")
@limiter.limit("10/minute")
def register():
    data = parse_body(RegisterIn)
    user = service.register(data)
    pair = service.issue_tokens(user, *_client())
    return jsonify(_token_body(pair)), 201


@bp.post("/auth/login")
@limiter.limit("10/minute")
def login():
    data = parse_body(LoginIn)
    pair = service.login(data.email, data.password, *_client())
    return jsonify(_token_body(pair))


@bp.post("/auth/refresh")
@jwt_required(refresh=True)
def refresh():
    pair = service.rotate_refresh_token(get_jwt()["jti"], *_client())
    if _uses_bearer():
        return jsonify(_token_body(pair))
    response = jsonify({"ok": True})
    set_access_cookies(response, pair.access_token)
    set_refresh_cookies(response, pair.refresh_token)
    return response


@bp.post("/auth/logout")
@jwt_required(refresh=True)
def logout():
    service.logout(get_jwt()["jti"])
    response = jsonify({"ok": True})
    unset_jwt_cookies(response)
    return response


@bp.get("/me")
@jwt_required()
def me():
    return jsonify(user_to_dict(current_user))


@bp.patch("/me")
@jwt_required()
def update_me():
    user = service.update_profile(current_user, parse_body(ProfileUpdate))
    return jsonify(user_to_dict(user))


@bp.post("/me/password")
@jwt_required()
def change_password():
    service.change_password(current_user, parse_body(PasswordChange))
    response = jsonify({"ok": True, "message": "Đã đổi mật khẩu. Vui lòng đăng nhập lại."})
    unset_jwt_cookies(response)
    return response
