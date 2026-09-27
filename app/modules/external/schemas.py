from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.external.models import SCOPES
from app.modules.vocabulary.schemas import SOURCE_TYPES


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    default_collection_id: str | None = None


class KeyCreate(BaseModel):
    scopes: list[Literal[SCOPES]] = Field(default_factory=lambda: list(SCOPES))  # type: ignore[valid-type]


class CaptureContext(BaseModel):
    sentence: str | None = Field(default=None, max_length=2000)
    translation: str | None = Field(default=None, max_length=2000)
    source_title: str | None = Field(default=None, max_length=255)
    source_type: Literal[SOURCE_TYPES] | None = None  # type: ignore[valid-type]
    location: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=1000)


class CaptureIn(BaseModel):
    """Lenient payload: only ``word`` is required."""

    word: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", max_length=8)
    meaning: str | None = Field(default=None, max_length=2000)
    translation: str | None = Field(default=None, max_length=1000)
    translation_language: str | None = Field(default=None, max_length=8)
    part_of_speech: str | None = Field(default=None, max_length=30)
    phonetic: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=20)
    context: CaptureContext | None = None
    source: str | None = Field(default=None, max_length=64)
    collection_id: str | None = None

    @field_validator("meaning", "translation", "part_of_speech", "phonetic")
    @classmethod
    def _blank(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("context", mode="before")
    @classmethod
    def _string_context(cls, value):
        return {"sentence": value} if isinstance(value, str) else value


def key_to_dict(key) -> dict:
    return {
        "id": key.id,
        "prefix": f"voca_{key.prefix}_…",
        "scopes": key.scopes,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "is_active": key.is_active,
    }


def application_to_dict(application) -> dict:
    return {
        "id": application.id,
        "name": application.name,
        "description": application.description,
        "default_collection_id": application.default_collection_id,
        "created_at": application.created_at.isoformat(),
        "keys": [key_to_dict(k) for k in application.keys],
    }
