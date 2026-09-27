from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Difficulty = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
SOURCE_TYPES = ("book", "article", "video", "caption", "chat", "course", "other")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _clean_list(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        v = v.strip()
        if v and v.lower() not in {s.lower() for s in seen}:
            seen[v] = None
    return list(seen)


class ExampleIn(BaseModel):
    sentence: str = Field(min_length=1, max_length=1000)
    translation: str | None = Field(default=None, max_length=1000)

    _c = field_validator("translation")(_clean)


class SenseIn(BaseModel):
    part_of_speech: str | None = Field(default=None, max_length=30)
    definition: str | None = Field(default=None, max_length=2000)
    translation: str | None = Field(default=None, max_length=1000)
    translation_language: str | None = Field(default=None, max_length=8)
    synonyms: list[str] = Field(default_factory=list, max_length=30)
    antonyms: list[str] = Field(default_factory=list, max_length=30)
    examples: list[ExampleIn] = Field(default_factory=list, max_length=10)

    _c = field_validator("part_of_speech", "definition", "translation", "translation_language")(_clean)
    _l = field_validator("synonyms", "antonyms")(_clean_list)

    @model_validator(mode="after")
    def _needs_meaning(self):
        if not self.definition and not self.translation:
            raise ValueError("Mỗi nghĩa cần có định nghĩa hoặc bản dịch")
        return self


class ContextIn(BaseModel):
    sentence: str | None = Field(default=None, max_length=2000)
    translation: str | None = Field(default=None, max_length=2000)
    source_id: str | None = None
    source_title: str | None = Field(default=None, max_length=255)
    source_type: Literal[SOURCE_TYPES] | None = None  # type: ignore[valid-type]
    location: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=1000)
    captured_via: str | None = Field(default=None, max_length=64)

    _c = field_validator("sentence", "translation", "source_title", "location", "url")(_clean)

    @model_validator(mode="after")
    def _not_empty(self):
        if not (self.sentence or self.source_id or self.source_title or self.url):
            raise ValueError("Ngữ cảnh cần có câu, nguồn hoặc liên kết")
        return self


class VocabularyCreate(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", max_length=8)
    phonetic: str | None = Field(default=None, max_length=200)
    difficulty: Difficulty | None = None
    notes: str | None = Field(default=None, max_length=5000)
    attributes: dict = Field(default_factory=dict)
    senses: list[SenseIn] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    contexts: list[ContextIn] = Field(default_factory=list, max_length=20)
    collection_ids: list[str] = Field(default_factory=list, max_length=20)

    _c = field_validator("phonetic", "notes")(_clean)
    _l = field_validator("tags")(_clean_list)

    @field_validator("word")
    @classmethod
    def _word(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Từ không được để trống")
        return value

    @field_validator("difficulty", mode="before")
    @classmethod
    def _blank_difficulty(cls, value):
        return value or None


class VocabularyUpdate(BaseModel):
    """Fields left out are unchanged; ``senses`` and ``tags`` replace the whole list."""

    word: str | None = Field(default=None, min_length=1, max_length=200)
    phonetic: str | None = Field(default=None, max_length=200)
    difficulty: Difficulty | None = None
    notes: str | None = Field(default=None, max_length=5000)
    attributes: dict | None = None
    senses: list[SenseIn] | None = Field(default=None, max_length=20)
    tags: list[str] | None = Field(default=None, max_length=20)

    _c = field_validator("phonetic", "notes")(_clean)

    @field_validator("difficulty", mode="before")
    @classmethod
    def _blank_difficulty(cls, value):
        return value or None


class VocabularyQuery(BaseModel):
    q: str | None = Field(default=None, max_length=200)
    collection_id: str | None = None
    tag: str | None = None
    status: Literal["NEW", "LEARNING", "REVIEWING", "MASTERED", "SUSPENDED", "DUE"] | None = None
    difficulty: Difficulty | None = None
    language: str | None = None
    source_id: str | None = None
    sort: Literal["newest", "oldest", "alpha", "due"] = "newest"
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=30, ge=1, le=100)

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v not in ("", None)}
        return data


class SourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    type: Literal[SOURCE_TYPES] = "other"  # type: ignore[valid-type]
    url: str | None = Field(default=None, max_length=1000)
    author: str | None = Field(default=None, max_length=255)


# ------------------------------------------------------------------ output

def progress_to_dict(progress) -> dict:
    if progress is None:
        return {"status": "NEW", "due_at": None, "interval_days": 0, "review_count": 0, "correct_count": 0, "wrong_count": 0}
    return {
        "status": progress.status,
        "due_at": progress.due_at.isoformat() if progress.due_at else None,
        "interval_days": progress.interval_days,
        "ease_factor": progress.ease_factor,
        "review_count": progress.review_count,
        "correct_count": progress.correct_count,
        "wrong_count": progress.wrong_count,
        "lapses": progress.lapses,
        "last_reviewed_at": progress.last_reviewed_at.isoformat() if progress.last_reviewed_at else None,
    }


def context_to_dict(ctx) -> dict:
    return {
        "id": ctx.id,
        "sentence": ctx.sentence,
        "translation": ctx.translation,
        "location": ctx.location,
        "url": ctx.url,
        "captured_via": ctx.captured_via,
        "captured_at": ctx.captured_at.isoformat(),
        "source": {"id": ctx.source.id, "title": ctx.source.title, "type": ctx.source.type} if ctx.source else None,
    }


def vocabulary_to_dict(vocab, progress=None, *, detail: bool = True) -> dict:
    data = {
        "id": vocab.id,
        "word": vocab.text,
        "language": vocab.language_code,
        "phonetic": vocab.phonetic,
        "difficulty": vocab.difficulty,
        "meaning": vocab.primary_meaning,
        "tags": [t.name for t in vocab.tags],
        "owner_id": vocab.owner_id,
        "source_type": vocab.source_type,
        "enrichment_status": vocab.enrichment_status,
        "created_at": vocab.created_at.isoformat(),
        "progress": progress_to_dict(progress),
    }
    if detail:
        data.update(
            notes=vocab.notes,
            attributes=vocab.attributes or {},
            senses=[
                {
                    "id": s.id,
                    "part_of_speech": s.part_of_speech,
                    "definition": s.definition,
                    "translation": s.translation,
                    "translation_language": s.translation_language_code,
                    "synonyms": s.synonyms or [],
                    "antonyms": s.antonyms or [],
                    "examples": [{"sentence": e.sentence, "translation": e.translation} for e in s.examples],
                }
                for s in vocab.senses
            ],
            contexts=[context_to_dict(c) for c in vocab.contexts],
            updated_at=vocab.updated_at.isoformat(),
        )
    return data
