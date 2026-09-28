from __future__ import annotations

from datetime import date, timedelta

from flask import current_app, flash, g, make_response, redirect, render_template, request, url_for
from flask_jwt_extended import set_access_cookies, set_refresh_cookies, unset_jwt_cookies

from app.core.clock import local_today, utcnow
from app.core.errors import AppError, ValidationFailed
from app.core.validation import parse_data
from app.extensions import db, limiter
from app.modules.auth import service as auth_service
from app.modules.auth.schemas import LoginIn, RegisterIn
from app.modules.collections import access
from app.modules.collections import service as collections_service
from app.modules.collections.models import CollectionWord
from app.modules.external import service as external_service
from app.modules.learning import planner
from app.modules.learning import service as learning_service
from app.modules.stats import service as stats_service
from app.modules.vocabulary import service as vocabulary_service
from app.modules.vocabulary.schemas import VocabularyQuery, vocabulary_to_dict
from app.web import bp, form_csrf_token, login_required, safe_next

TIMEZONES = [
    "Asia/Ho_Chi_Minh", "Asia/Bangkok", "Asia/Singapore", "Asia/Tokyo", "Asia/Seoul", "Asia/Shanghai",
    "Australia/Sydney", "Europe/London", "Europe/Paris", "Europe/Berlin", "America/New_York",
    "America/Chicago", "America/Los_Angeles", "UTC",
]


def _error_text(err: AppError) -> str:
    if isinstance(err, ValidationFailed) and err.details:
        return "; ".join(d["message"].removeprefix("Value error, ") for d in err.details)
    return err.message


def _login_response(pair, target: str):
    response = redirect(target)
    set_access_cookies(response, pair.access_token)
    set_refresh_cookies(response, pair.refresh_token)
    return response


# ---------------------------------------------------------------- auth pages

@bp.get("/")
def index():
    return redirect(url_for("web.dashboard" if g.user else "web.login"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def login():
    if request.method == "GET":
        if g.user:
            return redirect(safe_next(request.args.get("next")))
        return render_template("auth/login.html", next=request.args.get("next", ""))
    form = request.form
    try:
        data = parse_data(LoginIn, {"email": form.get("email", ""), "password": form.get("password", "")})
        pair = auth_service.login(data.email, data.password, request.headers.get("User-Agent"), request.remote_addr)
    except AppError as err:
        return render_template("auth/login.html", error=_error_text(err), email=form.get("email", ""), next=form.get("next", "")), 400
    return _login_response(pair, safe_next(form.get("next")))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def register():
    if request.method == "GET":
        return render_template("auth/register.html", timezones=TIMEZONES)
    form = request.form
    try:
        data = parse_data(
            RegisterIn,
            {
                "email": form.get("email", ""),
                "password": form.get("password", ""),
                "display_name": form.get("display_name", ""),
                "timezone": form.get("timezone") or None,
            },
        )
        user = auth_service.register(data)
        pair = auth_service.issue_tokens(user, request.headers.get("User-Agent"), request.remote_addr)
    except AppError as err:
        return render_template("auth/register.html", error=_error_text(err), form=form, timezones=TIMEZONES), 400
    flash("Chào mừng bạn đến với Voca! Hãy thêm những từ đầu tiên.", "success")
    return _login_response(pair, url_for("web.vocabulary_new"))


@bp.post("/logout")
def logout():
    from app.web import _decode

    sent = request.form.get("csrf_token", "")
    expected = request.cookies.get(current_app.config["JWT_REFRESH_CSRF_COOKIE_NAME"], "")
    refresh = _decode(request.cookies.get(current_app.config["JWT_REFRESH_COOKIE_NAME"]), "refresh")
    if refresh and sent and sent in (expected, form_csrf_token()):
        auth_service.logout(refresh["jti"])
    g.pop("pending_tokens", None)
    response = redirect(url_for("web.login"))
    unset_jwt_cookies(response)
    return response


# ---------------------------------------------------------------- dashboard & stats

def _heatmap(user, weeks: int) -> dict:
    """Grid of `weeks` columns x 7 rows (Mon..Sun) ending this week, with 0-4 intensity levels."""
    today = local_today(utcnow(), user.tz)
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    by_day = {row["date"]: row for row in stats_service.calendar(user, (today - start).days + 1)}
    peak = max((r["reviews"] for r in by_day.values()), default=0)
    columns = []
    for w in range(weeks):
        column = []
        for d in range(7):
            day = start + timedelta(days=7 * w + d)
            row = by_day.get(day.isoformat())
            reviews = row["reviews"] if row else 0
            level = 0 if reviews == 0 or peak == 0 else min(4, 1 + int(3 * reviews / peak))
            column.append({"date": day, "reviews": reviews, "level": level, "future": day > today,
                           "accuracy": round(100 * row["correct"] / reviews) if row and reviews else None})
        columns.append(column)
    months = []
    for i, column in enumerate(columns):
        first = column[0]["date"]
        starts_month = i == 0 or first.month != columns[i - 1][0]["date"].month
        if starts_month and (not months or i - months[-1]["index"] >= 3):  # avoid overlapping labels
            months.append({"index": i, "label": f"Th{first.month}"})
    return {"columns": columns, "months": months, "total_days": sum(1 for c in columns for d in c if d["reviews"])}


@bp.get("/dashboard")
@login_required
def dashboard():
    user = g.user
    plans = planner.list_plans(user.id, active_only=True)
    return render_template(
        "dashboard.html",
        today=stats_service.today(user),
        overview=stats_service.overview(user),
        heatmap=_heatmap(user, 17),
        plans=[(p, planner.plan_overview(user, p)) for p in plans],
    )


@bp.get("/statistics")
@login_required
def statistics():
    user = g.user
    calendar = stats_service.calendar(user, 30)
    return render_template(
        "statistics.html",
        overview=stats_service.overview(user),
        today=stats_service.today(user),
        heatmap=_heatmap(user, 53),
        recent=list(reversed(calendar)),
    )


# ---------------------------------------------------------------- vocabulary

def _word_list_context():
    query = parse_data(VocabularyQuery, request.args.to_dict())
    items, total = vocabulary_service.search(g.user.id, query)
    progress = vocabulary_service.progress_map(g.user.id, [v.id for v in items])
    pages = max(1, -(-total // query.per_page))
    return {
        "items": [vocabulary_to_dict(v, progress.get(v.id), detail=False) for v in items],
        "total": total,
        "query": query,
        "pages": pages,
        "args": {k: v for k, v in request.args.items() if k != "page" and v},
    }


@bp.get("/vocabulary")
@login_required
def vocabulary():
    ctx = _word_list_context()
    return render_template(
        "vocabulary/list.html",
        tags=vocabulary_service.list_tags(g.user.id),
        collections=collections_service.list_collections(g.user.id, "mine"),
        sources=vocabulary_service.list_sources(g.user.id),
        **ctx,
    )


@bp.get("/vocabulary/_list")
@login_required
def vocabulary_list_partial():
    ctx = _word_list_context()
    response = make_response(render_template("vocabulary/_list.html", **ctx))
    page_args = dict(ctx["args"], **({"page": ctx["query"].page} if ctx["query"].page > 1 else {}))
    response.headers["HX-Push-Url"] = url_for("web.vocabulary", **page_args)
    return response


def _form_options():
    mine = collections_service.list_collections(g.user.id, "mine")
    shared = [row for row in collections_service.list_collections(g.user.id, "shared") if row[1] == "editor"]
    return {
        "languages": vocabulary_service.list_languages(),
        "collections": [{"id": c.id, "name": c.name} for c, _, _ in mine + shared],
        "sources": [{"id": s.id, "title": s.title} for s in vocabulary_service.list_sources(g.user.id)],
    }


@bp.get("/vocabulary/new")
@login_required
def vocabulary_new():
    preset = {"collection_ids": [request.args["collection_id"]]} if request.args.get("collection_id") else {}
    return render_template("vocabulary/form.html", word=None, preset=preset, **_form_options())


@bp.get("/vocabulary/<vocab_id>")
@login_required
def vocabulary_detail(vocab_id: str):
    vocab = vocabulary_service.get_for_read(g.user.id, vocab_id)
    progress = vocabulary_service.progress_map(g.user.id, [vocab.id]).get(vocab.id)
    return render_template(
        "vocabulary/detail.html",
        word=vocabulary_to_dict(vocab, progress),
        progress=progress,
        can_edit=access.can_edit_vocabulary(g.user.id, vocab),
        is_owner=vocab.owner_id == g.user.id,
        collections=collections_service.collections_of_word(g.user.id, vocab.id),
        sources=[{"id": s.id, "title": s.title} for s in vocabulary_service.list_sources(g.user.id)],
    )


@bp.get("/vocabulary/<vocab_id>/edit")
@login_required
def vocabulary_edit(vocab_id: str):
    vocab = vocabulary_service.get_for_write(g.user.id, vocab_id)
    return render_template("vocabulary/form.html", word=vocabulary_to_dict(vocab), preset={}, **_form_options())


# ---------------------------------------------------------------- collections

@bp.get("/collections")
@login_required
def collections():
    scope = request.args.get("scope", "mine")
    if scope not in ("mine", "shared", "public"):
        scope = "mine"
    rows = collections_service.list_collections(g.user.id, scope)
    counts = collections_service.word_counts([c.id for c, _, _ in rows])
    depths = collections_service.depth_map([c for c, _, _ in rows]) if scope == "mine" else {}
    row_ids = {c.id for c, _, _ in rows}
    plans = {p.collection_id: (p, planner.plan_overview(g.user, p)) for p in planner.list_plans(g.user.id) if p.collection_id in row_ids}
    return render_template(
        "collections/list.html",
        scope=scope,
        rows=rows,
        counts=counts,
        plans=plans,
        depths=depths,
        parents=[c for c, _, _ in collections_service.list_collections(g.user.id, "mine") if not c.is_system],
    )


@bp.get("/collections/<collection_id>")
@login_required
def collection_detail(collection_id: str):
    collection, role = collections_service.get_readable(g.user.id, collection_id)
    plan = planner.get_plan(g.user.id, collection.id)
    request_args = request.args.to_dict() | {"collection_id": collection.id}
    query = parse_data(VocabularyQuery, request_args)
    items, total = vocabulary_service.search(g.user.id, query)
    progress = vocabulary_service.progress_map(g.user.id, [v.id for v in items])
    members = collections_service.list_members(g.user.id, collection.id) if role in ("owner", "editor", "viewer") else []
    mine = collections_service.list_collections(g.user.id, "mine")
    return render_template(
        "collections/detail.html",
        collection=collection,
        role=role,
        can_edit=access.can_edit(role),
        membership=collections_service.membership(collection.id, g.user.id),
        members=members,
        items=[vocabulary_to_dict(v, progress.get(v.id), detail=False) for v in items],
        total=total,
        query=query,
        pages=max(1, -(-total // query.per_page)),
        args={k: v for k, v in request.args.items() if k != "page" and v},
        children=[c for c, _, _ in mine if c.parent_id == collection.id],
        parent=collections_service.get_readable(g.user.id, collection.parent_id)[0] if collection.parent_id and role == "owner" else None,
        parents=[c for c, _, _ in mine if not c.is_system and c.id != collection.id],
        plan=plan,
        overview=planner.plan_overview(g.user, plan) if plan else None,
    )


@bp.get("/collections/<collection_id>/_candidates")
@login_required
def collection_candidates(collection_id: str):
    collections_service.get_editable(g.user.id, collection_id)
    query = parse_data(VocabularyQuery, {"q": request.args.get("q", ""), "per_page": 20})
    items, _ = vocabulary_service.search(g.user.id, query)
    in_collection = set(
        db.session.scalars(
            access.collection_vocabulary_ids(collection_id).where(CollectionWord.vocabulary_id.in_([v.id for v in items]))
        )
    )
    return render_template("collections/_candidates.html", items=items, collection_id=collection_id, in_collection=in_collection)


@bp.get("/join/<token>")
@login_required
def join_by_token(token: str):
    collection = collections_service.get_by_share_token(token)
    if collection.owner_id != g.user.id:
        collections_service.join(g.user.id, collection.id, token)
        flash(f"Bạn đã tham gia bộ từ “{collection.name}”.", "success")
    return redirect(url_for("web.collection_detail", collection_id=collection.id))


# ---------------------------------------------------------------- learn & settings

@bp.get("/learn")
@login_required
def learn():
    collection_id = request.args.get("collection_id") or None
    collection = collections_service.get_readable(g.user.id, collection_id)[0] if collection_id else None
    return render_template(
        "learn/index.html",
        collection=collection,
        plans=planner.list_plans(g.user.id, active_only=True),
        summary=learning_service.summary(g.user, collection_id),
        mode=request.args.get("mode", "flashcard"),
    )


@bp.get("/schedule")
@login_required
def schedule():
    collection_id = request.args.get("collection_id") or None
    collection = None
    if collection_id:
        collection = collections_service.get_readable(g.user.id, collection_id)[0]
        plan = planner.get_plan(g.user.id, collection_id)
        if plan is None or not plan.is_active:
            flash("Bộ từ này chưa được bắt đầu học nên chưa có lịch.", "info")
            return redirect(url_for("web.collection_detail", collection_id=collection_id))
    days = min(max(request.args.get("days", 14, type=int), 7), 60)
    plans = planner.list_plans(g.user.id, active_only=True)
    return render_template(
        "schedule.html",
        collection=collection,
        plans=plans,
        days=[dict(d, date_obj=date.fromisoformat(d["date"])) for d in planner.calendar(g.user, days, collection_id)] if plans else [],
        day_count=days,
    )


@bp.get("/settings")
@login_required
def settings():
    mine = collections_service.list_collections(g.user.id, "mine")
    return render_template(
        "settings.html",
        timezones=TIMEZONES if g.user.timezone in TIMEZONES else [g.user.timezone, *TIMEZONES],
        applications=external_service.list_applications(g.user.id),
        collections=[c for c, _, _ in mine],
        api_base=request.host_url.rstrip("/") + "/api/v1",
    )
