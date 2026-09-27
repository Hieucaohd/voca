from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.core.clock import is_valid_timezone

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 255:
        raise ValueError("Email không hợp lệ")
    return value


def _timezone(value: str | None) -> str | None:
    if value is not None and not is_valid_timezone(value):
        raise ValueError("Múi giờ không hợp lệ")
    return value


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    timezone: str | None = None

    _v_email = field_validator("email")(_email)
    _v_tz = field_validator("timezone")(_timezone)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Tên hiển thị không được để trống")
        return value


class LoginIn(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=128)

    _v_email = field_validator("email")(lambda v: v.strip().lower())


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = None
    native_language_code: str | None = Field(default=None, max_length=8)
    daily_new_limit: int | None = Field(default=None, ge=0, le=200)
    daily_review_limit: int | None = Field(default=None, ge=0, le=2000)
    daily_goal: int | None = Field(default=None, ge=1, le=1000)

    _v_tz = field_validator("timezone")(_timezone)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def user_to_dict(user) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "native_language_code": user.native_language_code,
        "timezone": user.timezone,
        "daily_new_limit": user.daily_new_limit,
        "daily_review_limit": user.daily_review_limit,
        "daily_goal": user.daily_goal,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
