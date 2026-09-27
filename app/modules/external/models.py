from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TimestampMixin, UTCDateTime, id_column, utcnow
from app.extensions import db

SCOPES = ("vocabulary:write", "vocabulary:read")


class ExternalApplication(TimestampMixin, db.Model):
    """An app a user connects: browser extension, realtime caption app, chat bot..."""

    __tablename__ = "external_applications"

    id: Mapped[str] = id_column()
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("collections.id", ondelete="SET NULL"), nullable=True
    )

    keys: Mapped[list[ApiKey]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApiKey.created_at"
    )


class ApiKey(db.Model):
    """Only a SHA-256 of the secret is stored; the raw key is shown once."""

    __tablename__ = "api_keys"

    id: Mapped[str] = id_column()
    application_id: Mapped[str] = mapped_column(ForeignKey("external_applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    application: Mapped[ExternalApplication] = relationship(back_populates="keys")
    user = relationship("User")

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > utcnow()
