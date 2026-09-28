"""Dashboard numbers: today's goal, overall progress, streaks and the activity calendar."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.clock import local_day_bounds, local_today, utcnow
from app.extensions import db
from app.modules.auth.models import User
from app.modules.learning import planner
from app.modules.learning.engine import ACTIVE_STATUSES, Status
from app.modules.learning.models import CardProgress, DailyActivity, ReviewLog
from app.modules.learning.service import summary as queue_summary
from app.modules.vocabulary.models import Vocabulary


def today(user: User) -> dict:
    now = utcnow()
    start, end = local_day_bounds(now, user.tz)
    activity = db.session.get(DailyActivity, (user.id, local_today(now, user.tz)))
    words_reviewed = db.session.scalar(
        select(func.count(func.distinct(ReviewLog.vocabulary_id))).where(
            ReviewLog.user_id == user.id, ReviewLog.reviewed_at >= start, ReviewLog.reviewed_at < end
        )
    ) or 0
    reviews = activity.reviews if activity else 0
    correct = activity.correct if activity else 0
    queue = queue_summary(user)
    return {
        "date": local_today(now, user.tz).isoformat(),
        "goal": user.daily_goal,
        "completed": words_reviewed,
        "goal_percent": min(100, round(100 * words_reviewed / user.daily_goal)) if user.daily_goal else 0,
        "reviews": reviews,
        "accuracy": round(100 * correct / reviews) if reviews else None,
        "new_learned": activity.new_learned if activity else 0,
        "new_remaining": queue["new_today"],
        "time_spent_minutes": round((activity.time_spent_ms if activity else 0) / 60000, 1),
        "due_remaining": queue["due"],
        "new_available": queue["new_today"],
    }


def streaks(active_days: set[date], today_: date) -> tuple[int, int]:
    """(current, longest). The current streak survives until the end of today."""
    current = 0
    cursor = today_ if today_ in active_days else today_ - timedelta(days=1)
    while cursor in active_days:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous = None
    for day in sorted(active_days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest


def overview(user: User) -> dict:
    now = utcnow()
    pool = planner.learning_pool_ids(user.id)
    total_own = db.session.scalar(select(func.count()).select_from(Vocabulary).where(Vocabulary.owner_id == user.id)) or 0
    total_pool = db.session.scalar(select(func.count()).select_from(Vocabulary).where(Vocabulary.id.in_(pool))) or 0

    counts = {s.value: 0 for s in Status}
    for status, count in db.session.execute(
        select(CardProgress.status, func.count())
        .where(CardProgress.user_id == user.id, CardProgress.vocabulary_id.in_(pool))
        .group_by(CardProgress.status)
    ):
        counts[status] = count
    started = sum(counts[s.value] for s in ACTIVE_STATUSES) + counts[Status.SUSPENDED.value]
    counts[Status.NEW.value] = max(0, total_pool - started)

    _, end = local_day_bounds(now, user.tz)
    due = db.session.scalar(
        select(func.count())
        .select_from(CardProgress)
        .where(
            CardProgress.user_id == user.id,
            CardProgress.status.in_([s.value for s in ACTIVE_STATUSES]),
            CardProgress.due_at < end,
            CardProgress.vocabulary_id.in_(pool),
        )
    ) or 0

    days = set(
        db.session.scalars(select(DailyActivity.local_date).where(DailyActivity.user_id == user.id, DailyActivity.reviews > 0))
    )
    current, longest = streaks(days, local_today(now, user.tz))
    totals = db.session.execute(
        select(func.coalesce(func.sum(DailyActivity.reviews), 0), func.coalesce(func.sum(DailyActivity.correct), 0))
        .where(DailyActivity.user_id == user.id)
    ).one()
    return {
        "total_words": total_own,
        "learning_pool": total_pool,
        "status_counts": counts,
        "learned": counts[Status.REVIEWING.value] + counts[Status.MASTERED.value],
        "mastered": counts[Status.MASTERED.value],
        "due_today": due,
        "streak": {"current": current, "longest": longest, "active_days": len(days)},
        "total_reviews": totals[0],
        "overall_accuracy": round(100 * totals[1] / totals[0]) if totals[0] else None,
    }


def calendar(user: User, days: int = 365) -> list[dict]:
    today_ = local_today(utcnow(), user.tz)
    start = today_ - timedelta(days=days - 1)
    rows = db.session.scalars(
        select(DailyActivity)
        .where(DailyActivity.user_id == user.id, DailyActivity.local_date >= start)
        .order_by(DailyActivity.local_date)
    )
    return [
        {
            "date": r.local_date.isoformat(),
            "reviews": r.reviews,
            "correct": r.correct,
            "new_learned": r.new_learned,
            "minutes": round(r.time_spent_ms / 60000, 1),
        }
        for r in rows
    ]
