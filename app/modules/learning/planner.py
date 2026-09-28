"""Study plans: which collections a learner is studying and what each day holds.

A word is only scheduled once the learner starts a collection that contains it.
New words are introduced in the order they were added to the collection,
``new_per_day`` at a time. Slots are computed on the fly, so a missed day
shifts the plan forward instead of piling words up, and words added later
simply join the end of the queue.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload

from app.core.clock import local_day_bounds, local_today, start_of_local_day, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.extensions import db
from app.modules.auth.models import User
from app.modules.collections import access
from app.modules.collections import service as collections_service
from app.modules.collections.models import Collection, CollectionWord
from app.modules.learning.engine import ACTIVE_STATUSES, Status
from app.modules.learning.models import PLAN_ACTIVE, PLAN_PAUSED, CardProgress, StudyPlan
from app.modules.vocabulary.models import Vocabulary

MAX_NEW_PER_DAY = 200
MAX_CALENDAR_DAYS = 60
_ACTIVE = [s.value for s in ACTIVE_STATUSES]


# ---------------------------------------------------------------- plans

def get_plan(user_id: str, collection_id: str) -> StudyPlan | None:
    return db.session.scalar(
        select(StudyPlan).where(StudyPlan.user_id == user_id, StudyPlan.collection_id == collection_id)
    )


def list_plans(user_id: str, *, active_only: bool = False) -> list[StudyPlan]:
    """Plans on collections the learner can still read, oldest first."""
    stmt = (
        select(StudyPlan)
        .join(Collection, Collection.id == StudyPlan.collection_id)
        .options(selectinload(StudyPlan.collection).selectinload(Collection.owner))
        .where(StudyPlan.user_id == user_id, access.readable_collections_filter(user_id))
        .order_by(StudyPlan.started_at, StudyPlan.id)
    )
    if active_only:
        stmt = stmt.where(StudyPlan.status == PLAN_ACTIVE)
    return list(db.session.scalars(stmt))


def _validate_new_per_day(value: int | None) -> None:
    if value is not None and not 0 <= value <= MAX_NEW_PER_DAY:
        raise ValidationFailed(f"Số từ mới mỗi ngày phải từ 0 đến {MAX_NEW_PER_DAY}")


def start(user: User, collection_id: str, new_per_day: int | None = None) -> StudyPlan:
    """Starts (or resumes) studying a collection. Joining a public collection happens implicitly."""
    _validate_new_per_day(new_per_day)
    collection, role = collections_service.get_readable(user.id, collection_id)
    if role == access.PUBLIC:
        collections_service.join(user.id, collection.id)
    plan = get_plan(user.id, collection.id)
    if plan is None:
        plan = StudyPlan(
            user_id=user.id,
            collection_id=collection.id,
            status=PLAN_ACTIVE,
            new_per_day=user.daily_new_limit if new_per_day is None else new_per_day,
            started_at=utcnow(),
        )
        db.session.add(plan)
    else:
        plan.status = PLAN_ACTIVE
        plan.paused_at = None
        if new_per_day is not None:
            plan.new_per_day = new_per_day
    db.session.commit()
    return plan


def update(user: User, collection_id: str, *, new_per_day: int | None = None, status: str | None = None) -> StudyPlan:
    _validate_new_per_day(new_per_day)
    collections_service.get_readable(user.id, collection_id)
    plan = get_plan(user.id, collection_id)
    if plan is None:
        raise NotFound("Bạn chưa bắt đầu học bộ từ này")
    if new_per_day is not None:
        plan.new_per_day = new_per_day
    if status == PLAN_PAUSED and plan.is_active:
        plan.status, plan.paused_at = PLAN_PAUSED, utcnow()
    elif status == PLAN_ACTIVE and not plan.is_active:
        plan.status, plan.paused_at = PLAN_ACTIVE, None
    db.session.commit()
    return plan


def remove(user: User, collection_id: str) -> None:
    """Stops studying and forgets the plan. Word progress is kept."""
    plan = get_plan(user.id, collection_id)
    if plan is None:
        raise NotFound("Bạn chưa bắt đầu học bộ từ này")
    db.session.delete(plan)
    db.session.commit()


def require_active_plan(user: User, collection_id: str) -> StudyPlan:
    collections_service.get_readable(user.id, collection_id)
    plan = get_plan(user.id, collection_id)
    if plan is None or not plan.is_active:
        raise Conflict("Bộ từ này chưa được bắt đầu học. Hãy bấm “Bắt đầu học” trước.", details={"reason": "NOT_STARTED"})
    return plan


# ---------------------------------------------------------------- word pools

def started_clause(user_id: str):
    """True once the learner has started a word (a NEW-status row still counts as not started)."""
    return exists().where(
        CardProgress.vocabulary_id == Vocabulary.id,
        CardProgress.user_id == user_id,
        CardProgress.status != Status.NEW.value,
    )


def pool_ids(collection_ids: list[str]):
    return select(CollectionWord.vocabulary_id).where(CollectionWord.collection_id.in_(collection_ids))


def learning_pool_ids(user_id: str):
    """Every word in the collections the learner is actively studying."""
    active = select(StudyPlan.collection_id).where(StudyPlan.user_id == user_id, StudyPlan.status == PLAN_ACTIVE)
    return select(CollectionWord.vocabulary_id).where(CollectionWord.collection_id.in_(active))


def _unseen_ids(user_id: str, collection_id: str, limit: int) -> list[str]:
    if limit <= 0:
        return []
    started = exists().where(
        CardProgress.vocabulary_id == CollectionWord.vocabulary_id,
        CardProgress.user_id == user_id,
        CardProgress.status != Status.NEW.value,
    )
    return list(
        db.session.scalars(
            select(CollectionWord.vocabulary_id)
            .where(CollectionWord.collection_id == collection_id, ~started)
            .order_by(CollectionWord.added_at, CollectionWord.vocabulary_id)
            .limit(limit)
        )
    )


def _unseen_count(user_id: str, collection_id: str) -> int:
    started = exists().where(
        CardProgress.vocabulary_id == CollectionWord.vocabulary_id,
        CardProgress.user_id == user_id,
        CardProgress.status != Status.NEW.value,
    )
    return db.session.scalar(
        select(func.count()).select_from(CollectionWord).where(CollectionWord.collection_id == collection_id, ~started)
    ) or 0


def _learned_today(user_id: str, collection_id: str, start: datetime, end: datetime) -> int:
    """New words from this collection that were studied for the first time today."""
    return db.session.scalar(
        select(func.count())
        .select_from(CardProgress)
        .where(
            CardProgress.user_id == user_id,
            CardProgress.first_reviewed_at >= start,
            CardProgress.first_reviewed_at < end,
            CardProgress.vocabulary_id.in_(pool_ids([collection_id])),
        )
    ) or 0


def _due_query(user_id: str, collection_ids: list[str], until: datetime):
    return select(CardProgress).where(
        CardProgress.user_id == user_id,
        CardProgress.status.in_(_ACTIVE),
        CardProgress.due_at < until,
        CardProgress.vocabulary_id.in_(pool_ids(collection_ids)),
    )


# ---------------------------------------------------------------- today

@dataclass
class TodayWork:
    due: list[CardProgress] = field(default_factory=list)
    new_ids: list[str] = field(default_factory=list)


def _plans_for(user: User, collection_id: str | None) -> list[StudyPlan]:
    if collection_id:
        return [require_active_plan(user, collection_id)]
    return list_plans(user.id, active_only=True)


def today_work(user: User, collection_id: str | None = None, limit: int | None = None) -> TodayWork:
    """Reviews due today plus today's remaining new words, for one collection or all active plans."""
    now = utcnow()
    start, end = local_day_bounds(now, user.tz)
    plans = _plans_for(user, collection_id)
    if not plans:
        return TodayWork()

    due = list(
        db.session.scalars(
            _due_query(user.id, [p.collection_id for p in plans], end)
            .order_by(CardProgress.due_at)
            .limit(limit or user.daily_review_limit)
        )
    )
    taken = {p.vocabulary_id for p in due}
    new_ids: list[str] = []
    for plan in plans:
        slots = new_slots_today(user, plan, start, end)
        if limit is not None:
            slots = min(slots, max(0, limit - len(due) - len(new_ids)))
        # Over-fetch by what is already taken: a word shared by two plans is introduced once.
        picked = 0
        for vid in _unseen_ids(user.id, plan.collection_id, slots + len(taken)):
            if picked >= slots:
                break
            if vid not in taken:
                taken.add(vid)
                new_ids.append(vid)
                picked += 1
    return TodayWork(due=due, new_ids=new_ids)


def new_slots_today(user: User, plan: StudyPlan, start: datetime, end: datetime) -> int:
    return max(0, plan.new_per_day - _learned_today(user.id, plan.collection_id, start, end))


def plan_overview(user: User, plan: StudyPlan) -> dict:
    """Numbers shown on a collection: today's work and overall progress."""
    now = utcnow()
    start, end = local_day_bounds(now, user.tz)
    total = db.session.scalar(
        select(func.count()).select_from(CollectionWord).where(CollectionWord.collection_id == plan.collection_id)
    ) or 0
    unseen = _unseen_count(user.id, plan.collection_id)
    learned_today = _learned_today(user.id, plan.collection_id, start, end)
    due = 0
    new_today = 0
    if plan.is_active:
        due = db.session.scalar(
            select(func.count()).select_from(_due_query(user.id, [plan.collection_id], end).subquery())
        ) or 0
        new_today = min(unseen, max(0, plan.new_per_day - learned_today))
    days_left = None
    if plan.is_active and plan.new_per_day:
        after_today = max(0, unseen - new_today)
        days_left = (1 if new_today else 0) + -(-after_today // plan.new_per_day)
    return {
        "collection_id": plan.collection_id,
        "status": plan.status,
        "new_per_day": plan.new_per_day,
        "started_at": plan.started_at.isoformat(),
        "total_words": total,
        "started_words": total - unseen,
        "unseen_words": unseen,
        "due_today": min(due, user.daily_review_limit),
        "new_today": new_today,
        "learned_today": learned_today,
        "todo_today": min(due, user.daily_review_limit) + new_today,
        "days_to_finish_new": days_left,
    }


def plan_to_dict(user: User, plan: StudyPlan) -> dict:
    data = plan_overview(user, plan)
    collection = plan.collection
    data["collection"] = {"id": collection.id, "name": collection.name, "owner": collection.owner.display_name if collection.owner else None}
    return data


# ---------------------------------------------------------------- calendar

@dataclass
class _Bucket:
    reviews: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)


def calendar(user: User, days: int = 14, collection_id: str | None = None) -> list[dict]:
    """Day-by-day schedule: which words of which collection are reviewed or introduced.

    Reviews use each word's real due date (overdue ones land on today). New words
    fill ``new_per_day`` slots per day in collection order. Reviews of words that
    are not learned yet are unknown until they are studied, so they are not shown.
    """
    days = max(1, min(days, MAX_CALENDAR_DAYS))
    now = utcnow()
    tz = user.tz
    today = local_today(now, tz)
    start, end_today = local_day_bounds(now, tz)
    horizon = start_of_local_day(today + timedelta(days=days), tz)
    plans = _plans_for(user, collection_id)

    grid: dict[date, dict[str, _Bucket]] = {today + timedelta(days=i): {} for i in range(days)}
    assigned: set[str] = set()

    for plan in plans:
        for progress in db.session.scalars(_due_query(user.id, [plan.collection_id], horizon).order_by(CardProgress.due_at)):
            if progress.vocabulary_id in assigned:
                continue
            assigned.add(progress.vocabulary_id)
            day = max(today, local_today(progress.due_at, tz))
            grid[day].setdefault(plan.collection_id, _Bucket()).reviews.append(progress.vocabulary_id)

    for plan in plans:
        if plan.new_per_day <= 0:
            continue
        today_slots = new_slots_today(user, plan, start, end_today)
        capacity = today_slots + plan.new_per_day * (days - 1)
        queue = [v for v in _unseen_ids(user.id, plan.collection_id, capacity + len(assigned)) if v not in assigned][:capacity]
        assigned.update(queue)
        cursor = 0
        for offset in range(days):
            size = today_slots if offset == 0 else plan.new_per_day
            chunk = queue[cursor:cursor + size]
            cursor += size
            if chunk:
                grid[today + timedelta(days=offset)].setdefault(plan.collection_id, _Bucket()).new.extend(chunk)

    words = _word_summaries(assigned)
    names = {p.collection_id: p.collection.name for p in plans}
    result = []
    for day, buckets in grid.items():
        groups = []
        for plan in plans:
            bucket = buckets.get(plan.collection_id)
            if bucket is None:
                continue
            groups.append(
                {
                    "collection_id": plan.collection_id,
                    "collection_name": names[plan.collection_id],
                    "reviews": [words[v] for v in bucket.reviews if v in words],
                    "new": [words[v] for v in bucket.new if v in words],
                }
            )
        result.append(
            {
                "date": day.isoformat(),
                "is_today": day == today,
                "review_count": sum(len(g["reviews"]) for g in groups),
                "new_count": sum(len(g["new"]) for g in groups),
                "collections": groups,
            }
        )
    return result


def _word_summaries(ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    vocabs = db.session.scalars(select(Vocabulary).options(selectinload(Vocabulary.senses)).where(Vocabulary.id.in_(ids)))
    return {v.id: {"id": v.id, "word": v.text, "meaning": v.primary_meaning} for v in vocabs}
