"""Scalar handling shared by the optional DataFrame adapters."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from bankparser.currencies import is_currency_code
from bankparser.errors import ParseError

_PLAIN_AMOUNT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def is_missing_scalar(value: Any) -> bool:
    """Recognize None, numeric NaN and nullable scalar sentinels without pandas.

    NaN and NaT compare unequal to themselves. pandas.NA cannot be converted
    to bool. Decimal NaNs are handled separately to avoid signaling-NaN traps.
    Source strings such as 'nan' remain ordinary data.
    """
    if value is None:
        return True
    if isinstance(value, Decimal):
        return value.is_nan()
    try:
        return bool(value != value)  # noqa: PLR0124
    except (TypeError, ValueError):
        return True


def scalar_text(value: Any) -> str | None:
    """Return optional text without stringifying a missing backend scalar."""
    if is_missing_scalar(value):
        return None
    return str(value).strip() or None


def validate_amount_text(value: str | None, *, location: str) -> None:
    """Reject exponent/non-finite notation before backend Decimal arithmetic.

    Plain decimal notation bounds coefficient digits and fractional scale by
    source length, so a short exponent cannot trigger enormous expanded sums.
    """
    if value is None or _PLAIN_AMOUNT.fullmatch(value.strip()) is None:
        raise ParseError(
            "Amount must use plain decimal notation without exponents",
            code="INVALID_AMOUNT",
            location=location,
        )


def currency_text(value: Any, *, location: str) -> str | None:
    """Validate original ASCII syntax before normalizing optional currency text."""
    text = scalar_text(value)
    if text is not None and not is_currency_code(text):
        raise ParseError(
            "Invalid currency code", code="INVALID_CURRENCY", location=location
        )
    return text.upper() if text is not None else None
