from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import DEFAULT_TZ, get_zone
from app.core.db import TimestampMixin, UTCDateTime, id_column, utcnow
from app.extensions import db


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[str] = id_column()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    native_language_code: Mapped[str] = mapped_column(String(8), default="vi")
    timezone: Mapped[str] = mapped_column(String(64), default=DEFAULT_TZ)
    daily_new_limit: Mapped[int] = mapped_column(Integer, default=10)
    daily_review_limit: Mapped[int] = mapped_column(Integer, default=100)
    daily_goal: Mapped[int] = mapped_column(Integer, default=20)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def tz(self) -> ZoneInfo:
        return get_zone(self.timezone)


class RefreshToken(db.Model):
    """One row per issued refresh token. Reuse of a rotated token revokes its whole family."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    replaced_by_jti: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
