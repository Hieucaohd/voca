"""Language-independent vocabulary model.

Language-specific details (Japanese reading, French gender, Korean
romanization...) live in ``Vocabulary.attributes`` instead of dedicated columns.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TimestampMixin, UTCDateTime, id_column, utcnow
from app.extensions import db


class Language(db.Model):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # ISO 639-1
    name: Mapped[str] = mapped_column(String(64))
    native_name: Mapped[str] = mapped_column(String(64))
    is_rtl: Mapped[bool] = mapped_column(Boolean, default=False)


vocabulary_tags = Table(
    "vocabulary_tags",
    db.metadata,
    Column("vocabulary_id", ForeignKey("vocabularies.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Vocabulary(TimestampMixin, db.Model):
    __tablename__ = "vocabularies"
    __table_args__ = (
        UniqueConstraint("owner_id", "language_code", "normalized_text"),
        Index("ix_vocabularies_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[str] = id_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    language_code: Mapped[str] = mapped_column(ForeignKey("languages.code"))
    text: Mapped[str] = mapped_column(String(200))
    normalized_text: Mapped[str] = mapped_column(String(200))
    phonetic: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    difficulty: Mapped[str | None] = mapped_column(String(4), nullable=True)  # CEFR A1..C2
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="manual")  # manual | external | import
    enrichment_status: Mapped[str] = mapped_column(String(20), default="none")  # none | pending | done | failed

    senses: Mapped[list[VocabularySense]] = relationship(
        back_populates="vocabulary", cascade="all, delete-orphan", order_by="VocabularySense.position"
    )
    contexts: Mapped[list[VocabularyContext]] = relationship(
        back_populates="vocabulary", cascade="all, delete-orphan", order_by="VocabularyContext.captured_at.desc()"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=vocabulary_tags, order_by="Tag.name")
    media: Mapped[list[MediaAsset]] = relationship(cascade="all, delete-orphan")

    @property
    def primary_meaning(self) -> str:
        """Short meaning shown on cards and used as the multiple-choice answer."""
        for sense in self.senses:
            if sense.translation:
                return sense.translation
        for sense in self.senses:
            if sense.definition:
                return sense.definition
        return ""


class VocabularySense(db.Model):
    __tablename__ = "vocabulary_senses"

    id: Mapped[str] = id_column()
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    part_of_speech: Mapped[str | None] = mapped_column(String(30), nullable=True)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation_language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    antonyms: Mapped[list] = mapped_column(JSON, default=list)

    vocabulary: Mapped[Vocabulary] = relationship(back_populates="senses")
    examples: Mapped[list[VocabularyExample]] = relationship(
        cascade="all, delete-orphan", order_by="VocabularyExample.position"
    )


class VocabularyExample(db.Model):
    __tablename__ = "vocabulary_examples"

    id: Mapped[str] = id_column()
    sense_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_senses.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    sentence: Mapped[str] = mapped_column(Text)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)


class Source(TimestampMixin, db.Model):
    """Where words are met: a book, article, video, caption session, chat..."""

    __tablename__ = "sources"
    __table_args__ = (Index("ix_sources_owner_title", "owner_id", "title"),)

    id: Mapped[str] = id_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20), default="other")
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class VocabularyContext(db.Model):
    """A sentence in which the learner met the word."""

    __tablename__ = "vocabulary_contexts"

    id: Mapped[str] = id_column()
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True)
    sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    captured_via: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    vocabulary: Mapped[Vocabulary] = relationship(back_populates="contexts")
    source: Mapped[Source | None] = relationship()


class Tag(db.Model):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name"),)

    id: Mapped[str] = id_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50))


class MediaAsset(db.Model):
    """Audio/image stored through the StorageBackend port (listening mode, later)."""

    __tablename__ = "media_assets"

    id: Mapped[str] = id_column()
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # audio | image
    storage_key: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(30))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
