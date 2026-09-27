"""Jinja filters for Vietnamese display."""
from __future__ import annotations

from datetime import datetime

from flask import g

from app.core.clock import get_zone, utcnow
from app.web import bp

STATUS_LABELS = {
    "NEW": "Mới",
    "LEARNING": "Đang học",
    "REVIEWING": "Đang ôn",
    "MASTERED": "Đã thuộc",
    "SUSPENDED": "Tạm ngưng",
}
VISIBILITY_LABELS = {"private": "Riêng tư", "shared": "Chia sẻ", "public": "Công khai"}
ROLE_LABELS = {"owner": "Chủ sở hữu", "editor": "Biên tập", "viewer": "Người xem", "public": "Công khai"}


@bp.app_template_filter("status_label")
def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "NEW", status or "")


@bp.app_template_filter("visibility_label")
def visibility_label(value: str) -> str:
    return VISIBILITY_LABELS.get(value, value)


@bp.app_template_filter("role_label")
def role_label(value: str | None) -> str:
    return ROLE_LABELS.get(value or "", value or "")


def _local(value: datetime) -> datetime:
    user = g.get("user")
    return value.astimezone(get_zone(user.timezone if user else None))


@bp.app_template_filter("localdate")
def localdate(value: datetime | None) -> str:
    return _local(value).strftime("%d/%m/%Y") if value else ""


@bp.app_template_filter("relative_due")
def relative_due(value: datetime | None) -> str:
    if value is None:
        return "—"
    now = utcnow()
    today = _local(now).date()
    day = _local(value).date()
    delta = (day - today).days
    if value <= now or delta < 0:
        return "Đến hạn"
    if delta == 0:
        return "Hôm nay"
    if delta == 1:
        return "Ngày mai"
    if delta < 30:
        return f"{delta} ngày nữa"
    if delta < 365:
        return f"{round(delta / 30)} tháng nữa"
    return f"{round(delta / 365, 1):g} năm nữa"
