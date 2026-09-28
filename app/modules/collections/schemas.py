from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    visibility: Literal["private", "shared", "public"] = "private"
    language_code: str | None = Field(default=None, max_length=8)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Tên bộ từ không được để trống")
        return value


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    parent_id: str | None = None
    visibility: Literal["private", "shared", "public"] | None = None


class WordIds(BaseModel):
    vocabulary_ids: list[str] = Field(min_length=1, max_length=500)


class ShareIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: Literal["viewer", "editor"] = "viewer"


class MemberUpdate(BaseModel):
    role: Literal["viewer", "editor"]


class JoinIn(BaseModel):
    token: str | None = None


def collection_to_dict(collection, role: str | None, word_count: int | None = None) -> dict:
    data = {
        "id": collection.id,
        "name": collection.name,
        "description": collection.description,
        "parent_id": collection.parent_id,
        "visibility": collection.visibility,
        "is_system": collection.is_system,
        "system_key": collection.system_key,
        "language_code": collection.language_code,
        "owner": {"id": collection.owner_id, "display_name": collection.owner.display_name if collection.owner else None},
        "role": role,
        "created_at": collection.created_at.isoformat(),
        "updated_at": collection.updated_at.isoformat(),
    }
    if word_count is not None:
        data["word_count"] = word_count
    if role == "owner":
        data["share_token"] = collection.share_token
    return data


def member_to_dict(member) -> dict:
    return {
        "user_id": member.user_id,
        "display_name": member.user.display_name,
        "email": member.user.email,
        "role": member.role,
        "joined_at": member.joined_at.isoformat(),
    }
