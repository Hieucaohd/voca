from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TimestampMixin, UTCDateTime, id_column, utcnow
from app.extensions import db

VISIBILITIES = ("private", "shared", "public")
MEMBER_ROLES = ("viewer", "editor")


class Collection(TimestampMixin, db.Model):
    __tablename__ = "collections"
    __table_args__ = (Index("ix_collections_visibility", "visibility"),)

    id: Mapped[str] = id_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str] = mapped_column(String(10), default="private")
    system_key: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "inbox"
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True)

    owner = relationship("User")

    @property
    def is_system(self) -> bool:
        return self.system_key is not None


class CollectionWord(db.Model):
    __tablename__ = "collection_words"

    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True)
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), primary_key=True, index=True)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class CollectionMember(db.Model):
    """Share permission. The owner is ``Collection.owner_id`` and is not stored here."""

    __tablename__ = "collection_members"
    __table_args__ = (UniqueConstraint("collection_id", "user_id"),)

    id: Mapped[str] = id_column()
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10), default="viewer")
    is_learning: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user = relationship("User")
