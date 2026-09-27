"""Application exceptions and a single JSON/HTML error format."""
from __future__ import annotations

import logging

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"
    default_message = "Yêu cầu không hợp lệ"

    def __init__(self, message: str | None = None, details=None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details


class ValidationFailed(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"
    default_message = "Dữ liệu không hợp lệ"


class AuthError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    default_message = "Bạn cần đăng nhập"


class PermissionDenied(AppError):
    status_code = 403
    code = "FORBIDDEN"
    default_message = "Bạn không có quyền thực hiện thao tác này"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"
    default_message = "Không tìm thấy"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"
    default_message = "Dữ liệu bị trùng"


def is_api_request() -> bool:
    return request.path.startswith("/api/")


def error_response(status: int, code: str, message: str, details=None):
    body = {"error": {"code": code, "message": message}, "request_id": getattr(g, "request_id", None)}
    if details is not None:
        body["error"]["details"] = details
    if is_api_request():
        return jsonify(body), status
    return render_template("errors/error.html", status=status, message=message), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        return error_response(err.status_code, err.code, err.message, err.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        code = (err.name or "error").upper().replace(" ", "_")
        messages = {404: "Không tìm thấy trang", 405: "Phương thức không được hỗ trợ", 429: "Bạn thao tác quá nhanh, hãy thử lại sau"}
        return error_response(err.code or 500, code, messages.get(err.code, err.description or "Lỗi"))

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        log.exception("unhandled_error")
        from app.extensions import db

        db.session.rollback()
        return error_response(500, "INTERNAL_ERROR", "Đã có lỗi xảy ra, vui lòng thử lại")
