"""External API gateway (API key auth) and key management (user JWT)."""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.core.validation import parse_body
from app.extensions import limiter
from app.modules.external import service
from app.modules.external.schemas import ApplicationCreate, BatchIn, CaptureIn, KeyCreate, application_to_dict, key_to_dict

# Called by browser extensions and other apps: CORS open, API-key auth, no cookies.
gateway = Blueprint("external_gateway", __name__)
# Managed from the web UI by the logged-in user.
manage = Blueprint("external_manage", __name__)


def _api_key_identity() -> str:
    raw = request.headers.get("X-API-Key", "")
    return raw.split("_")[1] if raw.count("_") >= 2 else (request.remote_addr or "anon")


@gateway.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


@gateway.before_request
def _authenticate():
    if request.method == "OPTIONS":
        return None
    scope = "vocabulary:write" if request.method == "POST" else "vocabulary:read"
    g.api_key = service.authenticate(request.headers.get("X-API-Key"), scope)
    return None


@gateway.post("/external/vocabulary")
@limiter.limit("120/minute", key_func=_api_key_identity)
def capture():
    result = service.capture(g.api_key, parse_body(CaptureIn))
    return jsonify(result), 201 if result["created"] else 200


@gateway.post("/external/vocabulary/batch")
@limiter.limit("30/minute", key_func=_api_key_identity)
def capture_batch():
    return jsonify(service.capture_many(g.api_key, parse_body(BatchIn)))


@gateway.get("/external/collections")
@limiter.limit("60/minute", key_func=_api_key_identity)
def list_collections():
    return jsonify({"items": service.list_target_collections(g.api_key)})


@gateway.get("/external/vocabulary/lookup")
@limiter.limit("300/minute", key_func=_api_key_identity)
def lookup():
    word = request.args.get("word", "").strip()
    if not word:
        return jsonify({"found": False})
    return jsonify(service.lookup(g.api_key, word, request.args.get("language", "en")))


@manage.get("/external/applications")
@jwt_required()
def list_applications():
    return jsonify({"items": [application_to_dict(a) for a in service.list_applications(current_user.id)]})


@manage.post("/external/applications")
@jwt_required()
def create_application():
    application = service.create_application(current_user.id, parse_body(ApplicationCreate))
    return jsonify(application_to_dict(application)), 201


@manage.delete("/external/applications/<app_id>")
@jwt_required()
def delete_application(app_id: str):
    service.delete_application(current_user.id, app_id)
    return "", 204


@manage.post("/external/applications/<app_id>/keys")
@jwt_required()
def create_key(app_id: str):
    scopes = parse_body(KeyCreate).scopes if request.is_json else None
    key, raw = service.create_key(current_user.id, app_id, scopes)
    body = key_to_dict(key)
    body["api_key"] = raw  # shown once
    return jsonify(body), 201


@manage.delete("/external/keys/<key_id>")
@jwt_required()
def revoke_key(key_id: str):
    service.revoke_key(current_user.id, key_id)
    return "", 204
