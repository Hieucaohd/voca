"""Authorization rules for collections and the words reachable through them.

Other modules ask these questions through this module instead of querying
collection tables themselves.
"""
from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.sql import Select

from app.extensions import db
from app.modules.collections.models import Collection, CollectionMember, CollectionWord
from app.modules.vocabulary.models import Vocabulary

OWNER, EDITOR, VIEWER, PUBLIC = "owner", "editor", "viewer", "public"
_RANK = {None: 0, PUBLIC: 1, VIEWER: 2, EDITOR: 3, OWNER: 4}


def role_for(user_id: str, collection: Collection) -> str | None:
    if collection.owner_id == user_id:
        return OWNER
    member_role = db.session.scalar(
        select(CollectionMember.role).where(
            CollectionMember.collection_id == collection.id, CollectionMember.user_id == user_id
        )
    )
    if member_role:
        return member_role
    if collection.visibility == "public":
        return PUBLIC
    return None


def can_read(role: str | None) -> bool:
    return _RANK[role] >= _RANK[PUBLIC]


def can_edit(role: str | None) -> bool:
    return _RANK[role] >= _RANK[EDITOR]


def _member_of(user_id: str, *roles: str):
    cond = [CollectionMember.collection_id == Collection.id, CollectionMember.user_id == user_id]
    if roles:
        cond.append(CollectionMember.role.in_(roles))
    return exists().where(*cond)


def readable_collections_filter(user_id: str):
    return or_(Collection.owner_id == user_id, Collection.visibility == "public", _member_of(user_id))


def can_read_vocabulary(user_id: str, vocab: Vocabulary) -> bool:
    if vocab.owner_id == user_id:
        return True
    stmt = (
        select(CollectionWord.vocabulary_id)
        .join(Collection, Collection.id == CollectionWord.collection_id)
        .where(CollectionWord.vocabulary_id == vocab.id, readable_collections_filter(user_id))
        .limit(1)
    )
    return db.session.scalar(stmt) is not None


def can_edit_vocabulary(user_id: str, vocab: Vocabulary) -> bool:
    """Owner, or editor/owner of a collection that contains the word."""
    if vocab.owner_id == user_id:
        return True
    stmt = (
        select(CollectionWord.vocabulary_id)
        .join(Collection, Collection.id == CollectionWord.collection_id)
        .where(
            CollectionWord.vocabulary_id == vocab.id,
            or_(Collection.owner_id == user_id, _member_of(user_id, EDITOR)),
        )
        .limit(1)
    )
    return db.session.scalar(stmt) is not None


def collection_vocabulary_ids(collection_id: str) -> Select:
    return select(CollectionWord.vocabulary_id).where(CollectionWord.collection_id == collection_id)
