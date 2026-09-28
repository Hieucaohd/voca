from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.core.validation import parse_body, parse_query
from app.modules.learning import planner, service
from app.modules.learning.schemas import QueueQuery, ReviewIn, StudyPlanIn
from app.modules.vocabulary.schemas import progress_to_dict

bp = Blueprint("learning_api", __name__)


@bp.get("/reviews/today")
@jwt_required()
def today():
    return jsonify(service.today_queue(current_user, parse_query(QueueQuery)))


@bp.get("/reviews/summary")
@jwt_required()
def summary():
    return jsonify(service.summary(current_user, request.args.get("collection_id") or None))


@bp.post("/reviews/<vocab_id>/result")
@jwt_required()
def submit(vocab_id: str):
    return jsonify(service.submit_review(current_user, vocab_id, parse_body(ReviewIn)))


@bp.post("/words/<vocab_id>/known")
@jwt_required()
def mark_known(vocab_id: str):
    return jsonify(progress_to_dict(service.mark_known(current_user, vocab_id)))


@bp.post("/words/<vocab_id>/suspend")
@jwt_required()
def suspend(vocab_id: str):
    return jsonify(progress_to_dict(service.suspend(current_user, vocab_id)))


@bp.post("/words/<vocab_id>/unsuspend")
@jwt_required()
def unsuspend(vocab_id: str):
    return jsonify(progress_to_dict(service.unsuspend(current_user, vocab_id)))


@bp.post("/words/<vocab_id>/reset")
@jwt_required()
def reset(vocab_id: str):
    return jsonify(progress_to_dict(service.reset(current_user, vocab_id)))


# ---------------------------------------------------------------- study plans

@bp.get("/study/plans")
@jwt_required()
def list_plans():
    return jsonify({"items": [planner.plan_to_dict(current_user, p) for p in planner.list_plans(current_user.id)]})


@bp.get("/collections/<collection_id>/study")
@jwt_required()
def get_plan(collection_id: str):
    service.summary(current_user, collection_id)  # access check
    plan = planner.get_plan(current_user.id, collection_id)
    if plan is None:
        return jsonify({"collection_id": collection_id, "status": None})
    return jsonify(planner.plan_to_dict(current_user, plan))


@bp.post("/collections/<collection_id>/study")
@jwt_required()
def start_plan(collection_id: str):
    data = parse_body(StudyPlanIn) if request.is_json else StudyPlanIn()
    plan = planner.start(current_user, collection_id, data.new_per_day)
    return jsonify(planner.plan_to_dict(current_user, plan)), 201


@bp.patch("/collections/<collection_id>/study")
@jwt_required()
def update_plan(collection_id: str):
    data = parse_body(StudyPlanIn)
    plan = planner.update(current_user, collection_id, new_per_day=data.new_per_day, status=data.status)
    return jsonify(planner.plan_to_dict(current_user, plan))


@bp.delete("/collections/<collection_id>/study")
@jwt_required()
def remove_plan(collection_id: str):
    planner.remove(current_user, collection_id)
    return "", 204


@bp.get("/study/calendar")
@jwt_required()
def calendar():
    days = request.args.get("days", 14, type=int)
    return jsonify({"days": planner.calendar(current_user, days, request.args.get("collection_id") or None)})
