from __future__ import annotations

from flask import Blueprint, jsonify, request
from flask_jwt_extended import current_user, jwt_required

from app.core.validation import parse_body
from app.modules.collections import service
from app.modules.collections.schemas import (
    CollectionCreate,
    CollectionUpdate,
    JoinIn,
    MemberUpdate,
    ShareIn,
    WordIds,
    collection_to_dict,
    member_to_dict,
)

bp = Blueprint("collections_api", __name__)


@bp.get("/collections")
@jwt_required()
def list_collections():
    rows = service.list_collections(current_user.id, request.args.get("scope", "mine"))
    counts = service.word_counts([c.id for c, _, _ in rows])
    return jsonify({"items": [collection_to_dict(c, role, counts.get(c.id, 0)) for c, role, _ in rows]})


@bp.post("/collections")
@jwt_required()
def create_collection():
    collection = service.create(current_user.id, parse_body(CollectionCreate))
    return jsonify(collection_to_dict(collection, "owner", 0)), 201


@bp.get("/collections/<collection_id>")
@jwt_required()
def get_collection(collection_id: str):
    collection, role = service.get_readable(current_user.id, collection_id)
    count = service.word_counts([collection.id]).get(collection.id, 0)
    return jsonify(collection_to_dict(collection, role, count))


@bp.patch("/collections/<collection_id>")
@jwt_required()
def update_collection(collection_id: str):
    collection = service.update(current_user.id, collection_id, parse_body(CollectionUpdate))
    return jsonify(collection_to_dict(collection, "owner"))


@bp.delete("/collections/<collection_id>")
@jwt_required()
def delete_collection(collection_id: str):
    service.delete_collection(current_user.id, collection_id)
    return "", 204


@bp.post("/collections/<collection_id>/words")
@jwt_required()
def add_words(collection_id: str):
    added = service.add_words(current_user.id, collection_id, parse_body(WordIds).vocabulary_ids)
    return jsonify({"added": added})


@bp.delete("/collections/<collection_id>/words/<vocabulary_id>")
@jwt_required()
def remove_word(collection_id: str, vocabulary_id: str):
    service.remove_word(current_user.id, collection_id, vocabulary_id)
    return "", 204


@bp.get("/collections/<collection_id>/members")
@jwt_required()
def list_members(collection_id: str):
    return jsonify({"items": [member_to_dict(m) for m in service.list_members(current_user.id, collection_id)]})


@bp.post("/collections/<collection_id>/share")
@jwt_required()
def share(collection_id: str):
    member = service.share(current_user.id, collection_id, parse_body(ShareIn))
    return jsonify(member_to_dict(member)), 201


@bp.post("/collections/<collection_id>/share-link")
@jwt_required()
def share_link(collection_id: str):
    enabled = (request.get_json(silent=True) or {}).get("enabled", True)
    collection = service.regenerate_share_token(current_user.id, collection_id, bool(enabled))
    return jsonify({"share_token": collection.share_token, "visibility": collection.visibility})


@bp.patch("/collections/<collection_id>/members/<user_id>")
@jwt_required()
def update_member(collection_id: str, user_id: str):
    member = service.update_member(current_user.id, collection_id, user_id, parse_body(MemberUpdate))
    return jsonify(member_to_dict(member))


@bp.delete("/collections/<collection_id>/members/<user_id>")
@jwt_required()
def remove_member(collection_id: str, user_id: str):
    service.remove_member(current_user.id, collection_id, user_id)
    return "", 204


@bp.post("/collections/<collection_id>/join")
@jwt_required()
def join(collection_id: str):
    token = parse_body(JoinIn).token if request.is_json else None
    member = service.join(current_user.id, collection_id, token)
    return jsonify({"collection_id": collection_id, "role": member.role})


@bp.post("/collections/<collection_id>/leave")
@jwt_required()
def leave(collection_id: str):
    service.remove_member(current_user.id, collection_id, current_user.id)
    return "", 204
