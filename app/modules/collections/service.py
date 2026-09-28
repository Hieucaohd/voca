"""Collections: nesting, words, sharing and membership."""
from __future__ import annotations

import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.extensions import db
from app.modules.auth.models import User
from app.modules.collections import access
from app.modules.collections.models import Collection, CollectionMember, CollectionWord
from app.modules.collections.schemas import CollectionCreate, CollectionUpdate, MemberUpdate, ShareIn
from app.modules.vocabulary.models import Vocabulary

INBOX_KEY = "inbox"
INBOX_NAME = "Hộp thư từ mới"


# ---------------------------------------------------------------- lookups

def _get(collection_id: str) -> Collection:
    collection = db.session.get(Collection, collection_id)
    if collection is None:
        raise NotFound("Không tìm thấy bộ từ")
    return collection


def get_readable(user_id: str, collection_id: str) -> tuple[Collection, str]:
    collection = _get(collection_id)
    role = access.role_for(user_id, collection)
    if not access.can_read(role):
        raise NotFound("Không tìm thấy bộ từ")  # do not reveal private collections
    return collection, role


def get_editable(user_id: str, collection_id: str) -> tuple[Collection, str]:
    collection, role = get_readable(user_id, collection_id)
    if not access.can_edit(role):
        raise PermissionDenied("Bạn chỉ có quyền xem bộ từ này")
    return collection, role


def get_owned(user_id: str, collection_id: str) -> Collection:
    collection, role = get_readable(user_id, collection_id)
    if role != access.OWNER:
        raise PermissionDenied("Chỉ chủ sở hữu mới làm được thao tác này")
    return collection


def ensure_inbox(user_id: str) -> Collection:
    inbox = db.session.scalar(
        select(Collection).where(Collection.owner_id == user_id, Collection.system_key == INBOX_KEY)
    )
    if inbox is None:
        inbox = Collection(owner_id=user_id, name=INBOX_NAME, system_key=INBOX_KEY, description="Từ được gửi từ ứng dụng khác")
        db.session.add(inbox)
        db.session.flush()
    return inbox


def word_counts(collection_ids: list[str]) -> dict[str, int]:
    if not collection_ids:
        return {}
    rows = db.session.execute(
        select(CollectionWord.collection_id, func.count())
        .where(CollectionWord.collection_id.in_(collection_ids))
        .group_by(CollectionWord.collection_id)
    )
    return {cid: count for cid, count in rows}


def list_collections(user_id: str, scope: str = "mine") -> list[tuple[Collection, str, CollectionMember | None]]:
    """Returns (collection, role, membership) tuples."""
    if scope == "mine":
        rows = db.session.scalars(
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(Collection.owner_id == user_id)
            .order_by(Collection.system_key.is_(None), Collection.name)
        ).all()
        return [(c, access.OWNER, None) for c in _tree_order(rows)]
    if scope == "shared":
        rows = db.session.execute(
            select(Collection, CollectionMember)
            .join(CollectionMember, CollectionMember.collection_id == Collection.id)
            .options(selectinload(Collection.owner))
            .where(CollectionMember.user_id == user_id)
            .order_by(Collection.name)
        ).all()
        return [(c, m.role, m) for c, m in rows]
    if scope == "public":
        rows = db.session.scalars(
            select(Collection)
            .options(selectinload(Collection.owner))
            .where(Collection.visibility == "public", Collection.owner_id != user_id)
            .order_by(Collection.updated_at.desc())
            .limit(100)
        ).all()
        return [(c, access.role_for(user_id, c), None) for c in rows]
    raise ValidationFailed("scope phải là mine, shared hoặc public")


def _tree_order(collections: list[Collection]) -> list[Collection]:
    """Parents first, each followed by its children (depth-first)."""
    by_parent: dict[str | None, list[Collection]] = {}
    ids = {c.id for c in collections}
    for c in collections:
        parent = c.parent_id if c.parent_id in ids else None
        by_parent.setdefault(parent, []).append(c)
    ordered: list[Collection] = []

    def walk(parent_id: str | None) -> None:
        for child in by_parent.get(parent_id, []):
            ordered.append(child)
            walk(child.id)

    walk(None)
    return ordered


def depth_map(collections: list[Collection]) -> dict[str, int]:
    parents = {c.id: c.parent_id for c in collections}
    depths: dict[str, int] = {}
    for cid in parents:
        depth, cursor, seen = 0, parents.get(cid), set()
        while cursor in parents and cursor not in seen:
            seen.add(cursor)
            depth += 1
            cursor = parents[cursor]
        depths[cid] = depth
    return depths


# ---------------------------------------------------------------- mutations

def _validate_parent(user_id: str, parent_id: str | None, collection_id: str | None = None) -> None:
    if parent_id is None:
        return
    parent = get_owned(user_id, parent_id)
    cursor = parent
    while cursor is not None:
        if cursor.id == collection_id:
            raise ValidationFailed("Không thể đặt bộ từ làm con của chính nó")
        cursor = db.session.get(Collection, cursor.parent_id) if cursor.parent_id else None


def create(user_id: str, data: CollectionCreate) -> Collection:
    _validate_parent(user_id, data.parent_id)
    collection = Collection(owner_id=user_id, **data.model_dump())
    db.session.add(collection)
    db.session.commit()
    return collection


def update(user_id: str, collection_id: str, data: CollectionUpdate) -> Collection:
    collection = get_owned(user_id, collection_id)
    changes = data.model_dump(exclude_unset=True)
    if collection.is_system and ({"visibility", "parent_id"} & changes.keys()):
        raise ValidationFailed("Không thể chia sẻ hoặc di chuyển hộp thư từ mới")
    if "parent_id" in changes:
        _validate_parent(user_id, changes["parent_id"], collection.id)
    for field, value in changes.items():
        if field == "name" and not value:
            continue
        setattr(collection, field, value)
    db.session.commit()
    return collection


def delete_collection(user_id: str, collection_id: str) -> None:
    collection = get_owned(user_id, collection_id)
    if collection.is_system:
        raise ValidationFailed("Không thể xoá hộp thư từ mới")
    # Children move up one level; words are kept (they belong to their owners).
    for child in db.session.scalars(select(Collection).where(Collection.parent_id == collection.id)):
        child.parent_id = collection.parent_id
    db.session.execute(delete(CollectionWord).where(CollectionWord.collection_id == collection.id))
    db.session.execute(delete(CollectionMember).where(CollectionMember.collection_id == collection.id))
    _delete_study_plans(collection.id)
    db.session.delete(collection)
    db.session.commit()


def add_words(user_id: str, collection_id: str, vocabulary_ids: list[str], *, commit: bool = True) -> int:
    collection, _ = get_editable(user_id, collection_id)
    wanted = list(dict.fromkeys(vocabulary_ids))
    vocabs = db.session.scalars(select(Vocabulary).where(Vocabulary.id.in_(wanted))).all()
    if len(vocabs) != len(wanted):
        raise NotFound("Có từ không tồn tại")
    for vocab in vocabs:
        if not access.can_read_vocabulary(user_id, vocab):
            raise NotFound("Có từ không tồn tại")
    existing = set(
        db.session.scalars(
            select(CollectionWord.vocabulary_id).where(
                CollectionWord.collection_id == collection.id, CollectionWord.vocabulary_id.in_(wanted)
            )
        )
    )
    added = 0
    for vid in wanted:
        if vid not in existing:
            db.session.add(CollectionWord(collection_id=collection.id, vocabulary_id=vid, added_by=user_id))
            added += 1
    if commit:
        db.session.commit()
    return added


def remove_word(user_id: str, collection_id: str, vocabulary_id: str) -> None:
    collection, _ = get_editable(user_id, collection_id)
    db.session.execute(
        delete(CollectionWord).where(
            CollectionWord.collection_id == collection.id, CollectionWord.vocabulary_id == vocabulary_id
        )
    )
    db.session.commit()


def collections_of_word(user_id: str, vocabulary_id: str) -> list[Collection]:
    return list(
        db.session.scalars(
            select(Collection)
            .join(CollectionWord, CollectionWord.collection_id == Collection.id)
            .where(CollectionWord.vocabulary_id == vocabulary_id, access.readable_collections_filter(user_id))
            .order_by(Collection.name)
        )
    )


# ---------------------------------------------------------------- sharing

def list_members(user_id: str, collection_id: str) -> list[CollectionMember]:
    collection, role = get_readable(user_id, collection_id)
    if role not in (access.OWNER, access.EDITOR, access.VIEWER):
        raise PermissionDenied()
    return list(
        db.session.scalars(
            select(CollectionMember)
            .options(selectinload(CollectionMember.user))
            .where(CollectionMember.collection_id == collection.id)
            .order_by(CollectionMember.joined_at)
        )
    )


def share(user_id: str, collection_id: str, data: ShareIn) -> CollectionMember:
    collection = get_owned(user_id, collection_id)
    if collection.is_system:
        raise ValidationFailed("Không thể chia sẻ hộp thư từ mới")
    target = db.session.scalar(select(User).where(User.email == data.email.strip().lower()))
    if target is None:
        raise NotFound("Không tìm thấy người dùng với email này")
    if target.id == user_id:
        raise ValidationFailed("Bạn đã là chủ sở hữu bộ từ này")
    member = membership(collection.id, target.id)
    if member is None:
        member = CollectionMember(collection_id=collection.id, user_id=target.id, role=data.role)
        db.session.add(member)
    else:
        member.role = data.role
    if collection.visibility == "private":
        collection.visibility = "shared"
    db.session.commit()
    return member


def update_member(user_id: str, collection_id: str, member_user_id: str, data: MemberUpdate) -> CollectionMember:
    get_owned(user_id, collection_id)
    member = membership(collection_id, member_user_id)
    if member is None:
        raise NotFound("Không tìm thấy thành viên")
    member.role = data.role
    db.session.commit()
    return member


def remove_member(user_id: str, collection_id: str, member_user_id: str) -> None:
    if member_user_id != user_id:
        get_owned(user_id, collection_id)
    member = membership(collection_id, member_user_id)
    if member is None:
        raise NotFound("Không tìm thấy thành viên")
    db.session.delete(member)
    collection = _get(collection_id)
    if collection.visibility != "public":  # access is gone, so is the study plan
        _delete_study_plans(collection_id, member_user_id)
    db.session.commit()


def join(user_id: str, collection_id: str, token: str | None = None) -> CollectionMember:
    collection = _get(collection_id)
    if collection.owner_id == user_id:
        raise Conflict("Bạn là chủ sở hữu bộ từ này")
    allowed = collection.visibility == "public" or (
        token is not None and collection.share_token is not None and secrets.compare_digest(token, collection.share_token)
    )
    if not allowed:
        raise NotFound("Không tìm thấy bộ từ")
    member = membership(collection.id, user_id)
    if member is None:
        member = CollectionMember(collection_id=collection.id, user_id=user_id, role="viewer")
        db.session.add(member)
        db.session.commit()
    return member


def get_by_share_token(token: str) -> Collection:
    collection = db.session.scalar(select(Collection).where(Collection.share_token == token))
    if collection is None:
        raise NotFound("Liên kết chia sẻ không hợp lệ")
    return collection


def regenerate_share_token(user_id: str, collection_id: str, enabled: bool = True) -> Collection:
    collection = get_owned(user_id, collection_id)
    if collection.is_system:
        raise ValidationFailed("Không thể chia sẻ hộp thư từ mới")
    collection.share_token = secrets.token_urlsafe(16) if enabled else None
    if enabled and collection.visibility == "private":
        collection.visibility = "shared"
    db.session.commit()
    return collection


def _delete_study_plans(collection_id: str, user_id: str | None = None) -> None:
    from app.modules.learning.models import StudyPlan  # learning depends on collections, not the reverse

    stmt = delete(StudyPlan).where(StudyPlan.collection_id == collection_id)
    if user_id is not None:
        stmt = stmt.where(StudyPlan.user_id == user_id)
    db.session.execute(stmt)


def membership(collection_id: str, user_id: str) -> CollectionMember | None:
    return db.session.scalar(
        select(CollectionMember).where(CollectionMember.collection_id == collection_id, CollectionMember.user_id == user_id)
    )
