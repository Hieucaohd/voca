from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.core.validation import parse_body, parse_query
from app.modules.learning import service
from app.modules.learning.schemas import QueueQuery, ReviewIn
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
