"""Simplified SM-2 with a fixed early ladder (1 -> 3 -> 7 -> 14 -> 30 days).

Early reviews follow a predictable ladder so beginners see the familiar
schedule; once past the ladder, the ease factor drives interval growth.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.clock import local_today, start_of_local_day
from app.modules.learning.engine.types import CardState, Grade, Status


@dataclass(frozen=True)
class SM2Config:
    ladder: tuple[int, ...] = (1, 3, 7, 14, 30)
    start_ease: float = 2.5
    min_ease: float = 1.3
    max_ease: float = 3.5
    again_ease_penalty: float = 0.20
    hard_ease_penalty: float = 0.15
    easy_ease_bonus: float = 0.15
    hard_multiplier: float = 1.2
    easy_multiplier: float = 1.3
    relearn_delay: timedelta = timedelta(minutes=10)
    mastered_interval_days: int = 30
    max_interval_days: int = 365 * 3
    fuzz_min_interval_days: int = 7
    fuzz_ratio: float = 0.05


class SM2Scheduler:
    def __init__(self, config: SM2Config | None = None, rng: random.Random | None = None) -> None:
        self.config = config or SM2Config()
        self.rng = rng  # None -> deterministic (no fuzz), used for previews and tests

    def schedule(self, state: CardState, grade: Grade, now: datetime, tz: ZoneInfo) -> CardState:
        cfg = self.config
        if grade == Grade.AGAIN:
            return replace(
                state,
                status=Status.LEARNING,
                repetitions=0,
                interval_days=0,
                ease_factor=self._clamp(state.ease_factor - cfg.again_ease_penalty),
                lapses=state.lapses + 1,
                due_at=now + cfg.relearn_delay,
            )

        reps = state.repetitions
        ease = state.ease_factor
        prev = state.interval_days

        if grade == Grade.HARD:
            ease = self._clamp(ease - cfg.hard_ease_penalty)
            interval = max(1, round(prev * cfg.hard_multiplier))
        elif grade == Grade.GOOD:
            reps += 1
            interval = self._ladder_or(reps, lambda: round(prev * ease))
        else:  # EASY
            ease = self._clamp(ease + cfg.easy_ease_bonus)
            reps += 2
            interval = self._ladder_or(reps, lambda: round(prev * ease * cfg.easy_multiplier))

        if reps > len(cfg.ladder) and grade != Grade.HARD:
            interval = max(interval, prev + 1)  # past the ladder a success always grows
        interval = min(self._fuzz(interval), cfg.max_interval_days)

        return replace(
            state,
            status=self._status_for(reps, interval),
            repetitions=reps,
            interval_days=interval,
            ease_factor=round(ease, 4),
            due_at=start_of_local_day(local_today(now, tz) + timedelta(days=interval), tz),
        )

    def preview(self, state: CardState, now: datetime, tz: ZoneInfo) -> dict[Grade, CardState]:
        """Outcome of each grade without randomness (for button labels)."""
        deterministic = SM2Scheduler(self.config, rng=None)
        return {g: deterministic.schedule(state, g, now, tz) for g in Grade}

    def _ladder_or(self, reps: int, beyond) -> int:
        ladder = self.config.ladder
        if reps <= len(ladder):
            return ladder[reps - 1]
        return max(1, beyond())

    def _status_for(self, reps: int, interval: int) -> Status:
        if interval >= self.config.mastered_interval_days:
            return Status.MASTERED
        if reps >= 2:
            return Status.REVIEWING
        return Status.LEARNING

    def _clamp(self, ease: float) -> float:
        return min(self.config.max_ease, max(self.config.min_ease, ease))

    def _fuzz(self, interval: int) -> int:
        if self.rng is None or interval < self.config.fuzz_min_interval_days:
            return interval
        spread = max(1, round(interval * self.config.fuzz_ratio))
        return max(1, interval + self.rng.randint(-spread, spread))
