"""JSON-safe serialization for canonical models."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any


def to_primitive(value: Any) -> Any:
    """Convert canonical dataclasses to JSON-safe primitives."""
    if dataclasses.is_dataclass(value):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [to_primitive(item) for item in value]
    if isinstance(value, list):
        return [to_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_primitive(item) for key, item in value.items()}
    return value
