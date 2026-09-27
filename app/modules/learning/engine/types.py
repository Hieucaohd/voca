"""Pure domain types for the spaced-repetition engine (no Flask/DB imports)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Protocol
from zoneinfo import ZoneInfo


class Grade(IntEnum):
    AGAIN = 0
    HARD = 1
    GOOD = 2
    EASY = 3

    @classmethod
    def parse(cls, value: int | str) -> "Grade":
        if isinstance(value, str) and not value.isdigit():
            return cls[value.upper()]
        return cls(int(value))


class Status(str, Enum):
    NEW = "NEW"
    LEARNING = "LEARNING"
    REVIEWING = "REVIEWING"
    MASTERED = "MASTERED"
    SUSPENDED = "SUSPENDED"


ACTIVE_STATUSES = (Status.LEARNING, Status.REVIEWING, Status.MASTERED)


@dataclass(frozen=True)
class CardState:
    status: Status = Status.NEW
    repetitions: int = 0          # consecutive successful recalls
    interval_days: int = 0
    ease_factor: float = 2.5
    lapses: int = 0
    due_at: datetime | None = None


class Scheduler(Protocol):
    def schedule(self, state: CardState, grade: Grade, now: datetime, tz: ZoneInfo) -> CardState: ...
