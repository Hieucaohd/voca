"""Learning use cases: today's queue, grading answers and applying the scheduler."""
from __future__ import annotations

import random
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload

from app.core.clock import local_today, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.text import normalize
from app.extensions import db
from app.modules.auth.models import User
from app.modules.collections import service as collections_service
from app.modules.learning import planner
from app.modules.learning.engine import (
    CardState,
    Grade,
    GradeResult,
    Scheduler,
    SM2Scheduler,
    Status,
    Verdict,
    grade_choice,
    grade_typing,
)
from app.modules.learning.models import CardProgress, DailyActivity, ReviewLog
from app.modules.learning.quiz import build_mcq, build_typing
from app.modules.learning.schemas import QueueQuery, ReviewIn
from app.modules.vocabulary import service as vocabulary_service
from app.modules.vocabulary.models import Vocabulary, VocabularySense
from app.modules.vocabulary.schemas import vocabulary_to_dict

MAX_RESPONSE_MS = 60_000  # cap idle time counted as study time
DISTRACTOR_POOL = 200


def get_scheduler() -> Scheduler:
    return SM2Scheduler(rng=random.Random())


def _preview_scheduler() -> SM2Scheduler:
    return SM2Scheduler(rng=None)


def format_interval(state: CardState, now: datetime) -> str:
    if state.interval_days == 0 and state.due_at is not None:
        minutes = max(1, round((state.due_at - now).total_seconds() / 60))
        return f"{minutes} phút"
    days = state.interval_days
    if days < 30:
        return f"{days} ngày"
    if days < 365:
        return f"{round(days / 30, 1):g} tháng"
    return f"{round(days / 365, 1):g} năm"


# ---------------------------------------------------------------- queue

def activity_for(user_id: str, day) -> DailyActivity | None:
    return db.session.get(DailyActivity, (user_id, day))


def summary(user: User, collection_id: str | None = None) -> dict:
    """Today's workload for one collection, or across every collection being studied."""
    if collection_id:
        collections_service.get_readable(user.id, collection_id)
        plan = planner.get_plan(user.id, collection_id)
        if plan is None:
            return {"started": False, "status": None, "due": 0, "new_today": 0, "todo": 0, "new_available": 0}
        overview = planner.plan_overview(user, plan)
        return {
            "started": True,
            "status": plan.status,
            "due": overview["due_today"],
            "new_today": overview["new_today"],
            "todo": overview["todo_today"],
            "new_available": overview["unseen_words"],
        }
    plans = planner.list_plans(user.id, active_only=True)
    work = planner.today_work(user)
    unseen = db.session.scalar(
        select(func.count())
        .select_from(Vocabulary)
        .where(Vocabulary.id.in_(planner.learning_pool_ids(user.id)), ~planner.started_clause(user.id))
    ) or 0
    return {
        "started": bool(plans),
        "plans": len(plans),
        "due": len(work.due),
        "new_today": len(work.new_ids),
        "todo": len(work.due) + len(work.new_ids),
        "new_available": unseen,
    }


def today_queue(user: User, query: QueueQuery) -> dict:
    now = utcnow()
    tz = user.tz
    work = planner.today_work(user, query.collection_id, query.limit)
    due_cards = work.due
    ids = [c.vocabulary_id for c in due_cards] + work.new_ids
    vocabs = {
        v.id: v
        for v in db.session.scalars(select(Vocabulary).options(*vocabulary_service.DETAIL_OPTIONS).where(Vocabulary.id.in_(ids)))
    } if ids else {}
    progress_by_vid = {c.vocabulary_id: c for c in due_cards}

    pool = planner.pool_ids([query.collection_id]) if query.collection_id else planner.learning_pool_ids(user.id)
    rng = random.Random()
    distractors = _distractor_pool(user, pool) if query.mode == "mcq" and ids else []
    preview = _preview_scheduler()

    items = []
    for vid in ids:
        vocab = vocabs.get(vid)
        if vocab is None or (not vocab.primary_meaning and query.mode != "flashcard"):
            continue  # a quiz needs a meaning
        progress = progress_by_vid.get(vid)
        state = progress.to_state() if progress else CardState()
        item = vocabulary_to_dict(vocab, progress)
        item["kind"] = "review" if progress else "new"
        item["preview"] = {g.name.lower(): format_interval(s, now) for g, s in preview.preview(state, now, tz).items()}
        if query.mode == "mcq":
            item["quiz"] = build_mcq(vocab, distractors, rng)
        elif query.mode == "typing":
            item["quiz"] = build_typing(vocab)
        items.append(item)

    return {"mode": query.mode, "items": items, "summary": summary(user, query.collection_id)}


def _distractor_pool(user: User, pool) -> list[Vocabulary]:
    stmt = (
        select(Vocabulary)
        .options(selectinload(Vocabulary.senses))
        .where(
            (Vocabulary.id.in_(pool)) | (Vocabulary.owner_id == user.id),
            exists().where(VocabularySense.vocabulary_id == Vocabulary.id),
        )
        .order_by(func.random())
        .limit(DISTRACTOR_POOL)
    )
    return list(db.session.scalars(stmt))


# ---------------------------------------------------------------- reviews

def _grade(vocab: Vocabulary, data: ReviewIn) -> tuple[GradeResult, str | None]:
    """Returns (grade result, correct answer to show)."""
    if data.mode == "flashcard":
        try:
            grade = Grade.parse(data.grade)
        except (KeyError, ValueError) as err:
            raise ValidationFailed("grade phải là again, hard, good hoặc easy") from err
        verdict = Verdict.WRONG if grade == Grade.AGAIN else Verdict.EXACT
        return GradeResult(grade, verdict), None
    if data.mode == "mcq":
        expected = vocab.primary_meaning
        correct = normalize(data.answer or "") == normalize(expected)
        return grade_choice(correct, data.confident, data.response_ms), expected
    expected = vocab.text
    return grade_typing(data.answer or "", expected, data.confident), expected


def _snapshot(state: CardState) -> dict:
    snap = asdict(state)
    snap["status"] = state.status.value
    snap["due_at"] = state.due_at.isoformat() if state.due_at else None
    return snap


def _review_result(log: ReviewLog, progress: CardProgress, correct_answer: str | None, now: datetime) -> dict:
    return {
        "vocabulary_id": log.vocabulary_id,
        "grade": Grade(log.grade).name.lower(),
        "is_correct": log.is_correct,
        "verdict": log.verdict,
        "correct_answer": correct_answer,
        "next_review_in": format_interval(progress.to_state(), now),
        "progress": {
            "status": progress.status,
            "due_at": progress.due_at.isoformat() if progress.due_at else None,
            "interval_days": progress.interval_days,
            "ease_factor": progress.ease_factor,
            "review_count": progress.review_count,
        },
    }


def submit_review(user: User, vocab_id: str, data: ReviewIn, scheduler: Scheduler | None = None) -> dict:
    now = utcnow()
    vocab = vocabulary_service.get_for_read(user.id, vocab_id)

    if data.client_review_id:
        previous = db.session.scalar(
            select(ReviewLog).where(ReviewLog.user_id == user.id, ReviewLog.client_review_id == data.client_review_id)
        )
        if previous is not None:  # idempotent retry
            progress = db.session.get(CardProgress, previous.card_progress_id)
            answer = vocab.primary_meaning if previous.mode == "mcq" else vocab.text if previous.mode == "typing" else None
            return _review_result(previous, progress, answer, now)

    result, correct_answer = _grade(vocab, data)

    progress = db.session.scalar(
        select(CardProgress).where(CardProgress.user_id == user.id, CardProgress.vocabulary_id == vocab.id)
    )
    is_new = progress is None or progress.review_count == 0
    if progress is None:
        progress = CardProgress(user_id=user.id, vocabulary_id=vocab.id, status=Status.NEW.value, ease_factor=2.5,
                                interval_days=0, repetitions=0, lapses=0, review_count=0, correct_count=0, wrong_count=0)
        db.session.add(progress)
        db.session.flush()
    elif progress.status == Status.SUSPENDED.value:
        raise Conflict("Từ này đang tạm ngưng ôn tập")

    before = progress.to_state()
    after = (scheduler or get_scheduler()).schedule(before, result.grade, now, user.tz)
    progress.apply_state(after)
    progress.review_count += 1
    if result.is_correct:
        progress.correct_count += 1
    else:
        progress.wrong_count += 1
    if is_new:
        progress.first_reviewed_at = now  # when the word was introduced (again, after a reset)
    progress.last_reviewed_at = now

    log = ReviewLog(
        user_id=user.id,
        card_progress_id=progress.id,
        vocabulary_id=vocab.id,
        mode=data.mode,
        grade=int(result.grade),
        is_correct=result.is_correct,
        verdict=result.verdict.value,
        answer_text=data.answer,
        response_ms=data.response_ms,
        prev_state=_snapshot(before),
        new_interval_days=after.interval_days,
        new_ease_factor=after.ease_factor,
        new_due_at=after.due_at,
        client_review_id=data.client_review_id,
        reviewed_at=now,
    )
    db.session.add(log)
    _record_activity(user, now, result.is_correct, is_new, data.response_ms)
    db.session.commit()
    return _review_result(log, progress, correct_answer, now)


def _record_activity(user: User, now: datetime, correct: bool, is_new: bool, response_ms: int | None) -> None:
    day = local_today(now, user.tz)
    activity = activity_for(user.id, day)
    if activity is None:
        activity = DailyActivity(user_id=user.id, local_date=day, reviews=0, correct=0, new_learned=0, time_spent_ms=0)
        db.session.add(activity)
    activity.reviews += 1
    activity.correct += int(correct)
    activity.new_learned += int(is_new)
    activity.time_spent_ms += min(response_ms or 0, MAX_RESPONSE_MS)


# ---------------------------------------------------------------- manual state changes

def _get_or_create_progress(user: User, vocab_id: str) -> CardProgress:
    vocab = vocabulary_service.get_for_read(user.id, vocab_id)
    progress = db.session.scalar(
        select(CardProgress).where(CardProgress.user_id == user.id, CardProgress.vocabulary_id == vocab.id)
    )
    if progress is None:
        progress = CardProgress(user_id=user.id, vocabulary_id=vocab.id, status=Status.NEW.value, ease_factor=2.5,
                                interval_days=0, repetitions=0, lapses=0, review_count=0, correct_count=0, wrong_count=0)
        db.session.add(progress)
    return progress


def mark_known(user: User, vocab_id: str) -> CardProgress:
    """"I already know this word": jump to the end of the ladder."""
    progress = _get_or_create_progress(user, vocab_id)
    scheduler = SM2Scheduler()
    ladder = scheduler.config.ladder
    now = utcnow()
    known = CardState(status=Status.MASTERED, repetitions=len(ladder) - 1, interval_days=ladder[-2],
                      ease_factor=progress.ease_factor or 2.5, lapses=progress.lapses)
    progress.apply_state(scheduler.schedule(known, Grade.GOOD, now, user.tz))
    progress.last_reviewed_at = now
    db.session.commit()
    return progress


def suspend(user: User, vocab_id: str) -> CardProgress:
    progress = _get_or_create_progress(user, vocab_id)
    progress.status = Status.SUSPENDED.value
    db.session.commit()
    return progress


def unsuspend(user: User, vocab_id: str) -> CardProgress:
    progress = db.session.scalar(
        select(CardProgress).where(CardProgress.user_id == user.id, CardProgress.vocabulary_id == vocab_id)
    )
    if progress is None or progress.status != Status.SUSPENDED.value:
        raise NotFound("Từ này không bị tạm ngưng")
    if progress.review_count == 0:
        progress.status = Status.NEW.value  # back to "not started"
    elif progress.interval_days >= SM2Scheduler().config.mastered_interval_days:
        progress.status = Status.MASTERED.value
    elif progress.repetitions >= 2:
        progress.status = Status.REVIEWING.value
    else:
        progress.status = Status.LEARNING.value
    progress.due_at = progress.due_at or utcnow()
    db.session.commit()
    return progress


def reset(user: User, vocab_id: str) -> CardProgress:
    """Start the word over as new. Review history is kept."""
    progress = _get_or_create_progress(user, vocab_id)
    progress.apply_state(CardState())
    progress.review_count = progress.correct_count = progress.wrong_count = 0
    db.session.commit()
    return progress
