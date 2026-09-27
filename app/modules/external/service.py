"""External applications, API keys and the vocabulary capture endpoint."""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.clock import utcnow
from app.core.errors import AuthError, NotFound, PermissionDenied
from app.core.text import normalize
from app.extensions import db
from app.modules.auth.models import User
from app.modules.collections import service as collections_service
from app.modules.external.models import SCOPES, ApiKey, ExternalApplication
from app.modules.external.schemas import ApplicationCreate, CaptureIn
from app.modules.vocabulary import service as vocabulary_service
from app.modules.vocabulary.models import Vocabulary
from app.modules.vocabulary.schemas import ContextIn, SenseIn, VocabularyCreate

log = logging.getLogger(__name__)

KEY_PREFIX = "voca"
LAST_USED_RESOLUTION = timedelta(minutes=5)  # avoid a DB write on every call


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


# ---------------------------------------------------------------- applications

def list_applications(user_id: str) -> list[ExternalApplication]:
    return list(
        db.session.scalars(
            select(ExternalApplication)
            .options(selectinload(ExternalApplication.keys))
            .where(ExternalApplication.owner_id == user_id)
            .order_by(ExternalApplication.created_at)
        )
    )


def _own_application(user_id: str, app_id: str) -> ExternalApplication:
    application = db.session.get(ExternalApplication, app_id)
    if application is None or application.owner_id != user_id:
        raise NotFound("Không tìm thấy ứng dụng")
    return application


def create_application(user_id: str, data: ApplicationCreate) -> ExternalApplication:
    if data.default_collection_id:
        collections_service.get_editable(user_id, data.default_collection_id)
    application = ExternalApplication(owner_id=user_id, **data.model_dump())
    db.session.add(application)
    db.session.commit()
    return application


def delete_application(user_id: str, app_id: str) -> None:
    db.session.delete(_own_application(user_id, app_id))
    db.session.commit()


def create_key(user_id: str, app_id: str, scopes: list[str] | None = None) -> tuple[ApiKey, str]:
    """Returns the key record and the raw key, which is never retrievable again."""
    application = _own_application(user_id, app_id)
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    key = ApiKey(
        application_id=application.id,
        user_id=user_id,
        prefix=prefix,
        key_hash=_hash(secret),
        scopes=list(scopes or SCOPES),
    )
    db.session.add(key)
    db.session.commit()
    return key, f"{KEY_PREFIX}_{prefix}_{secret}"


def revoke_key(user_id: str, key_id: str) -> None:
    key = db.session.get(ApiKey, key_id)
    if key is None or key.user_id != user_id:
        raise NotFound("Không tìm thấy khoá")
    key.revoked_at = key.revoked_at or utcnow()
    db.session.commit()


def authenticate(raw_key: str | None, scope: str) -> ApiKey:
    if not raw_key:
        raise AuthError("Thiếu API key (header X-API-Key)")
    parts = raw_key.strip().split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        raise AuthError("API key không hợp lệ")
    _, prefix, secret = parts
    key = db.session.scalar(select(ApiKey).options(selectinload(ApiKey.application)).where(ApiKey.prefix == prefix))
    if key is None or not hmac.compare_digest(key.key_hash, _hash(secret)):
        raise AuthError("API key không hợp lệ")
    if not key.is_active:
        raise AuthError("API key đã bị thu hồi hoặc hết hạn")
    if scope not in (key.scopes or []):
        raise PermissionDenied(f"API key thiếu quyền {scope}")
    user = db.session.get(User, key.user_id)
    if user is None or not user.is_active:
        raise AuthError("Tài khoản không khả dụng")
    now = utcnow()
    if key.last_used_at is None or now - key.last_used_at > LAST_USED_RESOLUTION:
        key.last_used_at = now
        db.session.commit()
    return key


# ---------------------------------------------------------------- capture

def _sense_from(data: CaptureIn) -> SenseIn | None:
    if not (data.meaning or data.translation):
        return None
    return SenseIn(
        part_of_speech=data.part_of_speech,
        definition=data.meaning,
        translation=data.translation,
        translation_language=data.translation_language,
        examples=[],
    )


def _context_from(data: CaptureIn, app_name: str) -> ContextIn | None:
    ctx = data.context
    if ctx is None:
        return None
    return ContextIn(
        sentence=ctx.sentence,
        translation=ctx.translation,
        source_title=ctx.source_title,
        source_type=ctx.source_type,
        location=ctx.location,
        url=ctx.url,
        captured_via=data.source or app_name,
    )


def _has_sense(vocab: Vocabulary, sense: SenseIn) -> bool:
    for existing in vocab.senses:
        if sense.translation and normalize(existing.translation or "") == normalize(sense.translation):
            return True
        if sense.definition and normalize(existing.definition or "") == normalize(sense.definition):
            return True
    return False


def capture(key: ApiKey, data: CaptureIn) -> dict:
    """Upsert: a new word is created; a known word only gains the new meaning/context."""
    user = db.session.get(User, key.user_id)
    application = key.application
    collection_id = data.collection_id or application.default_collection_id or collections_service.ensure_inbox(user.id).id
    sense = _sense_from(data)
    context = _context_from(data, application.name)

    vocab = vocabulary_service.find_by_text(user.id, data.language, data.word)
    if vocab is None:
        vocab = vocabulary_service.create_vocabulary(
            user,
            VocabularyCreate(
                word=data.word,
                language=data.language,
                phonetic=data.phonetic,
                senses=[sense] if sense else [],
                tags=data.tags,
                contexts=[context] if context else [],
                collection_ids=[collection_id],
            ),
            source_type="external",
            enrichment_status="none" if sense else "pending",
        )
        log.info("external_capture_created", extra={"fields": {"user_id": user.id, "app": application.id}})
        return {"id": vocab.id, "word": vocab.text, "created": True, "sense_added": sense is not None, "context_added": context is not None}

    sense_added = context_added = False
    if sense is not None and not _has_sense(vocab, sense):
        built = vocabulary_service.build_senses([sense], user.native_language_code)[0]
        built.position = len(vocab.senses)
        vocab.senses.append(built)
        if vocab.enrichment_status == "pending":
            vocab.enrichment_status = "done"
        sense_added = True
    if context is not None:
        duplicate = context.sentence and any(normalize(c.sentence or "") == normalize(context.sentence) for c in vocab.contexts)
        if not duplicate:
            vocab.contexts.append(vocabulary_service.build_context(user.id, context))
            context_added = True
    if not vocab.phonetic and data.phonetic:
        vocab.phonetic = data.phonetic
    collections_service.add_words(user.id, collection_id, [vocab.id], commit=False)
    vocab.updated_at = utcnow()
    db.session.commit()
    return {"id": vocab.id, "word": vocab.text, "created": False, "sense_added": sense_added, "context_added": context_added}


def lookup(key: ApiKey, word: str, language: str) -> dict:
    vocab = vocabulary_service.find_by_text(key.user_id, language, word)
    if vocab is None:
        return {"found": False}
    return {"found": True, "id": vocab.id, "word": vocab.text, "meaning": vocab.primary_meaning}

