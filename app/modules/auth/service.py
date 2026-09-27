"""Registration, credentials and refresh-token rotation."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from flask import current_app
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from sqlalchemy import select, update
from werkzeug.security import check_password_hash, generate_password_hash

from app.core.clock import utcnow
from app.core.errors import AuthError, Conflict, ValidationFailed
from app.extensions import db
from app.modules.auth.models import RefreshToken, User
from app.modules.auth.schemas import PasswordChange, ProfileUpdate, RegisterIn

log = logging.getLogger(__name__)

# Hash compared against when the email is unknown, so timing does not reveal accounts.
_DUMMY_HASH = generate_password_hash("voca-dummy-password")


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    user: User


def register(data: RegisterIn) -> User:
    if db.session.scalar(select(User.id).where(User.email == data.email)):
        raise Conflict("Email này đã được đăng ký")
    user = User(
        email=data.email,
        password_hash=generate_password_hash(data.password),
        display_name=data.display_name,
        timezone=data.timezone or current_app.config["DEFAULT_TIMEZONE"],
    )
    db.session.add(user)
    db.session.flush()

    from app.modules.collections import service as collections_service

    collections_service.ensure_inbox(user.id)
    db.session.commit()
    log.info("user_registered", extra={"fields": {"user_id": user.id}})
    return user


def authenticate(email: str, password: str) -> User:
    user = db.session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        raise AuthError("Email hoặc mật khẩu không đúng")
    if not check_password_hash(user.password_hash, password) or not user.is_active:
        raise AuthError("Email hoặc mật khẩu không đúng")
    user.last_login_at = utcnow()
    return user


def issue_tokens(
    user: User, user_agent: str | None = None, ip: str | None = None, family_id: str | None = None, *, commit: bool = True
) -> TokenPair:
    family_id = family_id or str(uuid.uuid4())
    access = create_access_token(identity=user.id)
    refresh = create_refresh_token(identity=user.id, additional_claims={"fam": family_id})
    claims = decode_token(refresh)
    db.session.add(
        RefreshToken(
            user_id=user.id,
            jti=claims["jti"],
            family_id=family_id,
            expires_at=datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
            user_agent=(user_agent or "")[:255] or None,
            ip=ip,
        )
    )
    if commit:
        db.session.commit()
    return TokenPair(access, refresh, user)


def login(email: str, password: str, user_agent: str | None = None, ip: str | None = None) -> TokenPair:
    user = authenticate(email, password)
    return issue_tokens(user, user_agent, ip)


def rotate_refresh_token(jti: str, user_agent: str | None = None, ip: str | None = None) -> TokenPair:
    record = db.session.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if record is None:
        raise AuthError("Phiên đăng nhập không hợp lệ")
    now = utcnow()
    if record.expires_at <= now:
        raise AuthError("Phiên đăng nhập đã hết hạn")

    user = db.session.get(User, record.user_id)
    if user is None or not user.is_active:
        raise AuthError("Tài khoản không khả dụng")

    if record.revoked_at is not None:
        grace = timedelta(seconds=current_app.config["REFRESH_REUSE_GRACE_SECONDS"])
        if record.replaced_by_jti and now - record.revoked_at <= grace:
            # Two tabs refreshing at the same moment: benign, issue another pair.
            return issue_tokens(user, user_agent, ip, family_id=record.family_id)
        revoke_family(record.family_id)
        log.warning("refresh_token_reuse", extra={"fields": {"user_id": user.id, "family": record.family_id}})
        raise AuthError("Phiên đăng nhập không hợp lệ, vui lòng đăng nhập lại")

    pair = issue_tokens(user, user_agent, ip, family_id=record.family_id, commit=False)
    record.revoked_at = now
    record.replaced_by_jti = decode_token(pair.refresh_token)["jti"]
    db.session.commit()
    return pair


def revoke_family(family_id: str) -> None:
    db.session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.session.commit()


def logout(refresh_jti: str) -> None:
    record = db.session.scalar(select(RefreshToken).where(RefreshToken.jti == refresh_jti))
    if record is not None:
        revoke_family(record.family_id)


def update_profile(user: User, data: ProfileUpdate) -> User:
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    db.session.commit()
    return user


def change_password(user: User, data: PasswordChange) -> None:
    if not check_password_hash(user.password_hash, data.current_password):
        raise ValidationFailed("Mật khẩu hiện tại không đúng")
    user.password_hash = generate_password_hash(data.new_password)
    db.session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.session.commit()
