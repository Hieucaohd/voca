from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import TimestampMixin, UTCDateTime, id_column, utcnow
from app.extensions import db
from app.modules.learning.engine import CardState, Status


class CardProgress(TimestampMixin, db.Model):
    """SRS state of one word for one learner (review schedule + progress counters)."""

    __tablename__ = "card_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "vocabulary_id"),
        Index("ix_card_progress_user_due", "user_id", "due_at"),
        Index("ix_card_progress_user_status", "user_id", "status"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), default=Status.NEW.value)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    repetitions: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    first_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    vocabulary = relationship("Vocabulary")

    def to_state(self) -> CardState:
        return CardState(
            status=Status(self.status),
            repetitions=self.repetitions,
            interval_days=self.interval_days,
            ease_factor=self.ease_factor,
            lapses=self.lapses,
            due_at=self.due_at,
        )

    def apply_state(self, state: CardState) -> None:
        self.status = state.status.value
        self.repetitions = state.repetitions
        self.interval_days = state.interval_days
        self.ease_factor = state.ease_factor
        self.lapses = state.lapses
        self.due_at = state.due_at


class ReviewLog(db.Model):
    """Append-only review history; enough to replay or migrate to another algorithm."""

    __tablename__ = "review_logs"
    __table_args__ = (
        Index("ix_review_logs_user_time", "user_id", "reviewed_at"),
        UniqueConstraint("user_id", "client_review_id"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    card_progress_id: Mapped[str] = mapped_column(ForeignKey("card_progress.id", ondelete="CASCADE"), index=True)
    vocabulary_id: Mapped[str] = mapped_column(ForeignKey("vocabularies.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(12))
    grade: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[bool] = mapped_column(default=False)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prev_state: Mapped[dict] = mapped_column(JSON, default=dict)
    new_interval_days: Mapped[int] = mapped_column(Integer)
    new_ease_factor: Mapped[float] = mapped_column(Float)
    new_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    client_review_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class DailyActivity(db.Model):
    """Per-user, per-local-day rollup for dashboard, streaks and the heatmap."""

    __tablename__ = "daily_activity"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reviews: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    new_learned: Mapped[int] = mapped_column(Integer, default=0)
    time_spent_ms: Mapped[int] = mapped_column(Integer, default=0)


PLAN_ACTIVE = "active"
PLAN_PAUSED = "paused"


class StudyPlan(TimestampMixin, db.Model):
    """A learner's decision to study one collection. Words only enter the schedule through an active plan."""

    __tablename__ = "study_plans"
    __table_args__ = (UniqueConstraint("user_id", "collection_id"),)

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(10), default=PLAN_ACTIVE)
    new_per_day: Mapped[int] = mapped_column(Integer, default=10)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    collection = relationship("Collection")

    @property
    def is_active(self) -> bool:
        return self.status == PLAN_ACTIVE

