from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.modules.stats import service

bp = Blueprint("stats_api", __name__)


@bp.get("/stats/today")
@jwt_required()
def today():
    return jsonify(service.today(current_user))


@bp.get("/stats/overview")
@jwt_required()
def overview():
    return jsonify(service.overview(current_user))


@bp.get("/stats/calendar")
@jwt_required()
def calendar():
    days = min(max(request.args.get("days", 365, type=int), 7), 730)
    return jsonify({"items": service.calendar(current_user, days)})
