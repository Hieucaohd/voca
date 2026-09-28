from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Mode = Literal["flashcard", "mcq", "typing"]


class QueueQuery(BaseModel):
    mode: Mode = "flashcard"
    collection_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=500)

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v not in ("", None)}
        return data


class ReviewIn(BaseModel):
    mode: Mode = "flashcard"
    grade: int | str | None = None
    answer: str | None = Field(default=None, max_length=1000)
    confident: bool = True
    response_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    client_review_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "flashcard" and self.grade is None:
            raise ValueError("Chế độ flashcard cần grade (again/hard/good/easy)")
        if self.mode in ("mcq", "typing") and self.answer is None:
            raise ValueError("Chế độ này cần câu trả lời (answer)")
        return self


class StudyPlanIn(BaseModel):
    new_per_day: int | None = Field(default=None, ge=0, le=200)
    status: Literal["active", "paused"] | None = None
