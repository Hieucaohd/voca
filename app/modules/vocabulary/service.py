"""Vocabulary use cases: create/update with senses, tags, contexts; search and filter."""
from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.clock import utcnow
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.text import normalize
from app.extensions import db
from app.modules.auth.models import User
from app.modules.collections import access
from app.modules.collections import service as collections_service
from app.modules.collections.models import CollectionWord
from app.modules.learning.engine import Status
from app.modules.learning.models import CardProgress
from app.modules.vocabulary.models import (
    Language,
    Source,
    Tag,
    Vocabulary,
    VocabularyContext,
    VocabularyExample,
    VocabularySense,
    vocabulary_tags,
)
from app.modules.vocabulary.schemas import ContextIn, SenseIn, SourceCreate, VocabularyCreate, VocabularyQuery, VocabularyUpdate

DETAIL_OPTIONS = (
    selectinload(Vocabulary.senses).selectinload(VocabularySense.examples),
    selectinload(Vocabulary.tags),
    selectinload(Vocabulary.contexts).selectinload(VocabularyContext.source),
)


# ---------------------------------------------------------------- reads

def _load(vocab_id: str) -> Vocabulary:
    vocab = db.session.scalar(select(Vocabulary).options(*DETAIL_OPTIONS).where(Vocabulary.id == vocab_id))
    if vocab is None:
        raise NotFound("Không tìm thấy từ")
    return vocab


def get_for_read(user_id: str, vocab_id: str) -> Vocabulary:
    vocab = _load(vocab_id)
    if not access.can_read_vocabulary(user_id, vocab):
        raise NotFound("Không tìm thấy từ")
    return vocab


def get_for_write(user_id: str, vocab_id: str) -> Vocabulary:
    vocab = get_for_read(user_id, vocab_id)
    if not access.can_edit_vocabulary(user_id, vocab):
        raise PermissionDenied("Bạn không có quyền sửa từ này")
    return vocab


def find_by_text(owner_id: str, language: str, text: str) -> Vocabulary | None:
    return db.session.scalar(
        select(Vocabulary)
        .options(*DETAIL_OPTIONS)
        .where(
            Vocabulary.owner_id == owner_id,
            Vocabulary.language_code == language,
            Vocabulary.normalized_text == normalize(text),
        )
    )


def progress_map(user_id: str, vocab_ids: list[str]) -> dict[str, CardProgress]:
    if not vocab_ids:
        return {}
    rows = db.session.scalars(
        select(CardProgress).where(CardProgress.user_id == user_id, CardProgress.vocabulary_id.in_(vocab_ids))
    )
    return {p.vocabulary_id: p for p in rows}


def search(user_id: str, query: VocabularyQuery) -> tuple[list[Vocabulary], int]:
    progress = CardProgress.__table__.alias("p")
    stmt = select(Vocabulary).outerjoin(
        progress, and_(progress.c.vocabulary_id == Vocabulary.id, progress.c.user_id == user_id)
    )

    if query.collection_id:
        collections_service.get_readable(user_id, query.collection_id)
        stmt = stmt.where(Vocabulary.id.in_(access.collection_vocabulary_ids(query.collection_id)))
    else:
        stmt = stmt.where(Vocabulary.owner_id == user_id)

    if query.q:
        term = f"%{normalize(query.q)}%"
        meaning_match = exists().where(
            VocabularySense.vocabulary_id == Vocabulary.id,
            or_(func.lower(VocabularySense.translation).like(term), func.lower(VocabularySense.definition).like(term)),
        )
        stmt = stmt.where(or_(Vocabulary.normalized_text.like(term), meaning_match))
    if query.tag:
        stmt = stmt.where(
            exists().where(
                vocabulary_tags.c.vocabulary_id == Vocabulary.id,
                vocabulary_tags.c.tag_id == Tag.id,
                func.lower(Tag.name) == query.tag.lower(),
            )
        )
    if query.difficulty:
        stmt = stmt.where(Vocabulary.difficulty == query.difficulty)
    if query.language:
        stmt = stmt.where(Vocabulary.language_code == query.language)
    if query.source_id:
        stmt = stmt.where(
            exists().where(VocabularyContext.vocabulary_id == Vocabulary.id, VocabularyContext.source_id == query.source_id)
        )
    if query.status == "NEW":
        stmt = stmt.where(or_(progress.c.id.is_(None), progress.c.status == Status.NEW.value))
    elif query.status == "DUE":
        stmt = stmt.where(progress.c.due_at <= utcnow().replace(tzinfo=None), progress.c.status != Status.SUSPENDED.value)
    elif query.status:
        stmt = stmt.where(progress.c.status == query.status)

    total = db.session.scalar(select(func.count()).select_from(stmt.subquery()))

    order = {
        "newest": [Vocabulary.created_at.desc()],
        "oldest": [Vocabulary.created_at.asc()],
        "alpha": [Vocabulary.normalized_text.asc()],
        "due": [progress.c.due_at.is_(None), progress.c.due_at.asc()],
    }[query.sort]
    items = db.session.scalars(
        stmt.options(selectinload(Vocabulary.senses), selectinload(Vocabulary.tags))
        .order_by(*order, Vocabulary.id)
        .limit(query.per_page)
        .offset((query.page - 1) * query.per_page)
    ).all()
    return list(items), total or 0


def list_tags(user_id: str) -> list[tuple[str, int]]:
    rows = db.session.execute(
        select(Tag.name, func.count(vocabulary_tags.c.vocabulary_id))
        .outerjoin(vocabulary_tags, vocabulary_tags.c.tag_id == Tag.id)
        .where(Tag.owner_id == user_id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    )
    return [(name, count) for name, count in rows]


def list_sources(user_id: str) -> list[Source]:
    return list(db.session.scalars(select(Source).where(Source.owner_id == user_id).order_by(Source.updated_at.desc())))


def list_languages() -> list[Language]:
    return list(db.session.scalars(select(Language).order_by(Language.name)))


# ---------------------------------------------------------------- writes

def _require_language(code: str) -> None:
    if db.session.get(Language, code) is None:
        raise ValidationFailed(f"Ngôn ngữ '{code}' chưa được hỗ trợ")


def build_senses(senses: list[SenseIn], default_translation_lang: str) -> list[VocabularySense]:
    built = []
    for i, s in enumerate(senses):
        sense = VocabularySense(
            position=i,
            part_of_speech=s.part_of_speech,
            definition=s.definition,
            translation=s.translation,
            translation_language_code=(s.translation_language or default_translation_lang) if s.translation else None,
            synonyms=s.synonyms,
            antonyms=s.antonyms,
        )
        sense.examples = [VocabularyExample(position=j, sentence=e.sentence.strip(), translation=e.translation) for j, e in enumerate(s.examples)]
        built.append(sense)
    return built


def resolve_tags(owner_id: str, names: list[str]) -> list[Tag]:
    if not names:
        return []
    existing = {
        t.name.lower(): t
        for t in db.session.scalars(select(Tag).where(Tag.owner_id == owner_id, func.lower(Tag.name).in_([n.lower() for n in names])))
    }
    tags = []
    for name in names:
        tag = existing.get(name.lower())
        if tag is None:
            tag = Tag(owner_id=owner_id, name=name[:50])
            db.session.add(tag)
            existing[name.lower()] = tag
        tags.append(tag)
    return tags


def _resolve_source(owner_id: str, ctx: ContextIn) -> Source | None:
    if ctx.source_id:
        source = db.session.get(Source, ctx.source_id)
        if source is None or source.owner_id != owner_id:
            raise NotFound("Không tìm thấy nguồn")
        return source
    if ctx.source_title:
        source = db.session.scalar(
            select(Source).where(Source.owner_id == owner_id, func.lower(Source.title) == ctx.source_title.lower())
        )
        if source is None:
            source = Source(owner_id=owner_id, title=ctx.source_title, type=ctx.source_type or "other", url=None)
            db.session.add(source)
        return source
    return None


def build_context(owner_id: str, ctx: ContextIn) -> VocabularyContext:
    return VocabularyContext(
        sentence=ctx.sentence,
        translation=ctx.translation,
        location=ctx.location,
        url=ctx.url,
        captured_via=ctx.captured_via,
        source=_resolve_source(owner_id, ctx),
    )


def create_vocabulary(
    user: User, data: VocabularyCreate, *, source_type: str = "manual", enrichment_status: str = "none", commit: bool = True
) -> Vocabulary:
    _require_language(data.language)
    existing = find_by_text(user.id, data.language, data.word)
    if existing is not None:
        raise Conflict("Từ này đã có trong kho của bạn", details={"existing_id": existing.id})

    vocab = Vocabulary(
        owner_id=user.id,
        language_code=data.language,
        text=data.word,
        normalized_text=normalize(data.word),
        phonetic=data.phonetic,
        difficulty=data.difficulty,
        notes=data.notes,
        attributes=data.attributes,
        source_type=source_type,
        enrichment_status=enrichment_status,
    )
    vocab.senses = build_senses(data.senses, user.native_language_code)
    vocab.tags = resolve_tags(user.id, data.tags)
    vocab.contexts = [build_context(user.id, c) for c in data.contexts]
    db.session.add(vocab)
    db.session.flush()

    # Every word lives in at least one collection, so it can be scheduled once that collection is started.
    for collection_id in data.collection_ids or [collections_service.ensure_inbox(user.id).id]:
        collections_service.add_words(user.id, collection_id, [vocab.id], commit=False)
    if commit:
        db.session.commit()
    return vocab


def update_vocabulary(user: User, vocab_id: str, data: VocabularyUpdate) -> Vocabulary:
    vocab = get_for_write(user.id, vocab_id)
    changes = data.model_dump(exclude_unset=True)

    if data.word is not None:
        word = " ".join(data.word.split())
        normalized = normalize(word)
        if normalized != vocab.normalized_text:
            clash = find_by_text(vocab.owner_id, vocab.language_code, word)
            if clash is not None and clash.id != vocab.id:
                raise Conflict("Từ này đã có trong kho", details={"existing_id": clash.id})
        vocab.text, vocab.normalized_text = word, normalized
    for field in ("phonetic", "difficulty", "notes"):
        if field in changes:
            setattr(vocab, field, getattr(data, field))
    if data.attributes is not None:
        vocab.attributes = data.attributes
    if data.senses is not None:
        vocab.senses = build_senses(data.senses, user.native_language_code)
        if vocab.senses and vocab.enrichment_status == "pending":
            vocab.enrichment_status = "done"
    if data.tags is not None:
        vocab.tags = resolve_tags(vocab.owner_id, data.tags)
    vocab.updated_at = utcnow()
    db.session.commit()
    return vocab


def delete_vocabulary(user: User, vocab_id: str) -> None:
    vocab = get_for_read(user.id, vocab_id)
    if vocab.owner_id != user.id:
        raise PermissionDenied("Chỉ người tạo mới xoá được từ này")
    # Explicit cleanup: FK cascades are not guaranteed on every libSQL connection.
    from app.modules.learning.models import ReviewLog

    db.session.execute(ReviewLog.__table__.delete().where(ReviewLog.vocabulary_id == vocab.id))
    db.session.execute(CardProgress.__table__.delete().where(CardProgress.vocabulary_id == vocab.id))
    db.session.execute(CollectionWord.__table__.delete().where(CollectionWord.vocabulary_id == vocab.id))
    db.session.delete(vocab)  # senses, contexts, media and tag links go through ORM cascades
    db.session.commit()


def add_context(user: User, vocab_id: str, data: ContextIn) -> VocabularyContext:
    vocab = get_for_write(user.id, vocab_id)
    context = build_context(vocab.owner_id, data)
    vocab.contexts.append(context)
    db.session.commit()
    return context


def delete_context(user: User, vocab_id: str, context_id: str) -> None:
    vocab = get_for_write(user.id, vocab_id)
    context = next((c for c in vocab.contexts if c.id == context_id), None)
    if context is None:
        raise NotFound("Không tìm thấy ngữ cảnh")
    vocab.contexts.remove(context)
    db.session.commit()


def create_source(user: User, data: SourceCreate) -> Source:
    source = Source(owner_id=user.id, **data.model_dump())
    db.session.add(source)
    db.session.commit()
    return source
