"""Structured JSON logs to stdout (Vercel collects stdout) with a per-request id."""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid

from flask import Flask, g, has_request_context, request


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if has_request_context():
            payload["request_id"] = getattr(g, "request_id", None)
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    access_log = logging.getLogger("voca.access")

    @app.before_request
    def _start_request():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def _log_request(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        if not request.path.startswith("/static/"):
            duration_ms = round((time.perf_counter() - g.get("request_started", time.perf_counter())) * 1000, 1)
            access_log.info(
                "request",
                extra={"fields": {"method": request.method, "path": request.path, "status": response.status_code, "ms": duration_ms}},
            )
        return response
