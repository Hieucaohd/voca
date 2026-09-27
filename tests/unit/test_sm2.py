import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.modules.learning.engine import CardState, Grade, SM2Scheduler, Status

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)  # 10:00 in Hanoi


def run(grades, scheduler=None, state=None):
    scheduler = scheduler or SM2Scheduler()
    state = state or CardState()
    history = []
    for g in grades:
        state = scheduler.schedule(state, g, NOW, TZ)
        history.append(state)
    return history


def test_good_answers_follow_ladder_then_ease():
    intervals = [s.interval_days for s in run([Grade.GOOD] * 7)]
    assert intervals[:5] == [1, 3, 7, 14, 30]
    assert intervals[5] == 75  # 30 * 2.5
    assert intervals[6] == round(75 * 2.5)


def test_statuses_progress():
    states = run([Grade.GOOD] * 5)
    assert [s.status for s in states] == [
        Status.LEARNING, Status.REVIEWING, Status.REVIEWING, Status.REVIEWING, Status.MASTERED,
    ]


def test_again_resets_and_relearns_in_ten_minutes():
    good = run([Grade.GOOD] * 3)[-1]
    lapsed = SM2Scheduler().schedule(good, Grade.AGAIN, NOW, TZ)
    assert lapsed.status == Status.LEARNING
    assert lapsed.repetitions == 0
    assert lapsed.lapses == 1
    assert lapsed.ease_factor == pytest.approx(2.3)
    assert lapsed.due_at == NOW + timedelta(minutes=10)
    assert SM2Scheduler().schedule(lapsed, Grade.GOOD, NOW, TZ).interval_days == 1


def test_due_is_local_midnight():
    state = SM2Scheduler().schedule(CardState(), Grade.GOOD, NOW, TZ)
    assert state.due_at.astimezone(TZ) == datetime(2026, 9, 29, 0, 0, tzinfo=TZ)


def test_hard_does_not_advance_and_lowers_ease():
    s = run([Grade.GOOD, Grade.GOOD])[-1]  # interval 3
    hard = SM2Scheduler().schedule(s, Grade.HARD, NOW, TZ)
    assert hard.repetitions == s.repetitions
    assert hard.interval_days == 4  # round(3 * 1.2)
    assert hard.ease_factor == pytest.approx(2.35)


def test_hard_on_new_card_is_one_day():
    state = SM2Scheduler().schedule(CardState(), Grade.HARD, NOW, TZ)
    assert state.interval_days == 1
    assert state.status == Status.LEARNING


def test_easy_skips_a_step():
    state = SM2Scheduler().schedule(CardState(), Grade.EASY, NOW, TZ)
    assert state.interval_days == 3
    assert state.status == Status.REVIEWING
    assert state.ease_factor == pytest.approx(2.65)


def test_ease_never_below_minimum():
    states = run([Grade.AGAIN] * 20)
    assert states[-1].ease_factor == pytest.approx(1.3)


def test_success_past_ladder_always_grows_even_with_low_ease():
    state = CardState(status=Status.MASTERED, repetitions=8, interval_days=40, ease_factor=1.3)
    nxt = SM2Scheduler().schedule(state, Grade.GOOD, NOW, TZ)
    assert nxt.interval_days > 40


def test_fuzz_stays_within_five_percent():
    base = CardState(status=Status.MASTERED, repetitions=6, interval_days=100, ease_factor=2.5)
    for seed in range(50):
        s = SM2Scheduler(rng=random.Random(seed)).schedule(base, Grade.GOOD, NOW, TZ)
        assert abs(s.interval_days - 250) <= 13


def test_interval_capped():
    state = CardState(status=Status.MASTERED, repetitions=20, interval_days=900, ease_factor=3.0)
    assert SM2Scheduler().schedule(state, Grade.EASY, NOW, TZ).interval_days == 365 * 3


def test_preview_is_deterministic_and_covers_all_grades():
    scheduler = SM2Scheduler(rng=random.Random(1))
    preview = scheduler.preview(CardState(), NOW, TZ)
    assert {g: s.interval_days for g, s in preview.items()} == {
        Grade.AGAIN: 0, Grade.HARD: 1, Grade.GOOD: 1, Grade.EASY: 3,
    }


@pytest.mark.parametrize("raw,expected", [("again", Grade.AGAIN), ("Easy", Grade.EASY), (2, Grade.GOOD), ("1", Grade.HARD)])
def test_grade_parse(raw, expected):
    assert Grade.parse(raw) == expected
