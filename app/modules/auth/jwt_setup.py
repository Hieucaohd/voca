"""Flask-JWT-Extended callbacks: user loading and errors in the app's JSON format."""
from __future__ import annotations

from flask_jwt_extended import JWTManager

from app.core.errors import error_response
from app.extensions import db
from app.modules.auth.models import User


def init_jwt(jwt: JWTManager) -> None:
    @jwt.user_lookup_loader
    def _load_user(_header, payload):
        user = db.session.get(User, payload["sub"])
        return user if user is not None and user.is_active else None

    @jwt.user_lookup_error_loader
    def _user_missing(_header, _payload):
        return error_response(401, "UNAUTHORIZED", "Tài khoản không khả dụng")

    @jwt.expired_token_loader
    def _expired(_header, _payload):
        return error_response(401, "TOKEN_EXPIRED", "Phiên đăng nhập đã hết hạn")

    @jwt.invalid_token_loader
    def _invalid(reason: str):
        return error_response(401, "INVALID_TOKEN", "Token không hợp lệ")

    @jwt.unauthorized_loader
    def _missing(reason: str):
        if "CSRF" in reason:
            return error_response(401, "CSRF_ERROR", "Thiếu CSRF token")
        return error_response(401, "UNAUTHORIZED", "Bạn cần đăng nhập")

    @jwt.needs_fresh_token_loader
    def _needs_fresh(_header, _payload):
        return error_response(401, "FRESH_TOKEN_REQUIRED", "Vui lòng đăng nhập lại")
