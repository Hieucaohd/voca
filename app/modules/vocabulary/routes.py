from __future__ import annotations

from flask import Blueprint, jsonify
from flask_jwt_extended import current_user, jwt_required

from app.core.validation import parse_body, parse_query
from app.modules.collections import service as collections_service
from app.modules.vocabulary import service
from app.modules.vocabulary.schemas import (
    ContextIn,
    SourceCreate,
    VocabularyCreate,
    VocabularyQuery,
    VocabularyUpdate,
    context_to_dict,
    vocabulary_to_dict,
)

bp = Blueprint("vocabulary_api", __name__)


def _detail(vocab) -> dict:
    progress = service.progress_map(current_user.id, [vocab.id]).get(vocab.id)
    data = vocabulary_to_dict(vocab, progress)
    data["collections"] = [
        {"id": c.id, "name": c.name} for c in collections_service.collections_of_word(current_user.id, vocab.id)
    ]
    return data


@bp.get("/words")
@jwt_required()
def list_words():
    query = parse_query(VocabularyQuery)
    items, total = service.search(current_user.id, query)
    progress = service.progress_map(current_user.id, [v.id for v in items])
    return jsonify(
        {
            "items": [vocabulary_to_dict(v, progress.get(v.id), detail=False) for v in items],
            "page": query.page,
            "per_page": query.per_page,
            "total": total,
        }
    )


@bp.post("/words")
@jwt_required()
def create_word():
    vocab = service.create_vocabulary(current_user, parse_body(VocabularyCreate))
    return jsonify(_detail(service.get_for_read(current_user.id, vocab.id))), 201


@bp.get("/words/<vocab_id>")
@jwt_required()
def get_word(vocab_id: str):
    return jsonify(_detail(service.get_for_read(current_user.id, vocab_id)))


@bp.put("/words/<vocab_id>")
@bp.patch("/words/<vocab_id>")
@jwt_required()
def update_word(vocab_id: str):
    vocab = service.update_vocabulary(current_user, vocab_id, parse_body(VocabularyUpdate))
    return jsonify(_detail(vocab))


@bp.delete("/words/<vocab_id>")
@jwt_required()
def delete_word(vocab_id: str):
    service.delete_vocabulary(current_user, vocab_id)
    return "", 204


@bp.post("/words/<vocab_id>/contexts")
@jwt_required()
def add_context(vocab_id: str):
    context = service.add_context(current_user, vocab_id, parse_body(ContextIn))
    return jsonify(context_to_dict(context)), 201


@bp.delete("/words/<vocab_id>/contexts/<context_id>")
@jwt_required()
def delete_context(vocab_id: str, context_id: str):
    service.delete_context(current_user, vocab_id, context_id)
    return "", 204


@bp.get("/tags")
@jwt_required()
def list_tags():
    return jsonify({"items": [{"name": n, "count": c} for n, c in service.list_tags(current_user.id)]})


@bp.get("/sources")
@jwt_required()
def list_sources():
    return jsonify(
        {"items": [{"id": s.id, "title": s.title, "type": s.type, "url": s.url, "author": s.author} for s in service.list_sources(current_user.id)]}
    )


@bp.post("/sources")
@jwt_required()
def create_source():
    s = service.create_source(current_user, parse_body(SourceCreate))
    return jsonify({"id": s.id, "title": s.title, "type": s.type, "url": s.url, "author": s.author}), 201


@bp.get("/languages")
def list_languages():
    return jsonify({"items": [{"code": lang.code, "name": lang.name, "native_name": lang.native_name} for lang in service.list_languages()]})
