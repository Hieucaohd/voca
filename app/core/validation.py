"""Request parsing with Pydantic, mapped onto the app's error format."""
from __future__ import annotations

from typing import TypeVar

from flask import request
from pydantic import BaseModel, ValidationError

from app.core.errors import ValidationFailed

T = TypeVar("T", bound=BaseModel)


def _details(err: ValidationError) -> list[dict]:
    return [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in err.errors()]


def parse_body(schema: type[T]) -> T:
    data = request.get_json(silent=True)
    if data is None:
        raise ValidationFailed("Nội dung yêu cầu phải là JSON")
    try:
        return schema.model_validate(data)
    except ValidationError as err:
        raise ValidationFailed(details=_details(err)) from err


def parse_query(schema: type[T]) -> T:
    try:
        return schema.model_validate(request.args.to_dict())
    except ValidationError as err:
        raise ValidationFailed(details=_details(err)) from err


def parse_data(schema: type[T], data: dict) -> T:
    try:
        return schema.model_validate(data)
    except ValidationError as err:
        raise ValidationFailed(details=_details(err)) from err
