"""Time helpers. The learner's "today" is always computed in their own timezone."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Ho_Chi_Minh"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["utcnow", "get_zone", "local_today", "local_day_bounds", "start_of_local_day", "is_valid_timezone"]


def get_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def local_today(now: datetime, tz: ZoneInfo) -> date:
    return now.astimezone(tz).date()


def start_of_local_day(day: date, tz: ZoneInfo) -> datetime:
    """Local midnight of ``day`` expressed in UTC."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def local_day_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of the learner's current day, in UTC."""
    today = local_today(now, tz)
    return start_of_local_day(today, tz), start_of_local_day(today + timedelta(days=1), tz)
