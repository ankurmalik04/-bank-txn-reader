"""Source-level safeguards shared by both MT940 adapters."""

from __future__ import annotations

import re
from datetime import date

from bankparser.errors import ParseError

_TAGS = re.compile(rb"(?m)^(?:\xef\xbb\xbf)?:(20|25|28C|60[FM]|61|62[FM]):([^\r\n]*)")
_TRANSACTION = re.compile(
    r"(?P<date>\d{6})(?P<entry_date>\d{4})?(?:RC|RD|EC|ED|C|D)"
    r"[A-Z]?[0-9,]+(?P<code>[A-Z][A-Z0-9]{3})(?P<reference>.*)",
    re.IGNORECASE,
)


def source_fields(data: bytes) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Reject multiple scopes and retain fields discarded by native parsers.

    Monetary values remain the responsibility of the selected parser. This
    function only reads boundaries, balance currencies, dates and references.
    """
    fields: dict[str, str] = {}
    transactions: list[dict[str, object]] = []
    line = 1
    cursor = 0
    for match in _TAGS.finditer(data):
        tag = match.group(1).decode("ascii")
        line += data[cursor : match.start()].count(b"\n")
        cursor = match.start()
        if tag != "61" and tag in fields:
            raise ParseError(
                f"Repeated MT940 :{tag}: tag; supply one statement per file",
                code="MULTIPLE_STATEMENTS",
                location=f"line {line} :{tag}:",
            )
        try:
            value = match.group(2).decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ParseError(
                "MT940 source fields must be UTF-8",
                code="INVALID_ENCODING",
                location=f"line {line} :{tag}:",
            ) from exc
        if tag != "61":
            fields[tag] = value
            continue
        parsed = _TRANSACTION.fullmatch(value)
        if parsed is None:
            raise ParseError(
                "Unsupported MT940 transaction structure",
                code="UNSUPPORTED_TRANSACTION",
                location=f"line {line} :61:",
            )
        try:
            value_date = _compact_date(parsed["date"])
            booking_date = _booking_date(value_date, parsed["entry_date"])
        except ValueError as exc:
            raise ParseError(
                "Invalid MT940 transaction date",
                code="INVALID_DATE",
                location=f"line {line} :61:",
            ) from exc
        customer, _, bank = parsed["reference"].partition("//")
        transactions.append(
            {
                "booking_date": booking_date,
                "customer_reference": customer.strip() or None,
                "bank_reference": bank.strip() or None,
                "source_line": line,
            }
        )
    if "60F" in fields and "60M" in fields or "62F" in fields and "62M" in fields:
        raise ParseError(
            "Multiple MT940 balance sections cannot be represented",
            code="MULTIPLE_STATEMENTS",
        )
    return fields, transactions


def balance_currency(fields: dict[str, str], tag: str) -> str | None:
    value = fields.get(tag)
    return (
        value[7:10].upper()
        if value and re.match(r"^[CD]\d{6}[A-Z]{3}", value)
        else None
    )


def _booking_date(value_date: date, entry_date: str | None) -> date | None:
    if entry_date is None:
        return None
    month, day = int(entry_date[:2]), int(entry_date[2:])
    candidates = []
    for year in (value_date.year - 1, value_date.year, value_date.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            pass
    if not candidates:
        raise ValueError("Invalid entry date")
    return min(candidates, key=lambda candidate: abs((candidate - value_date).days))


def _compact_date(text: str) -> date:
    year = int(text[:2])
    return date(
        2000 + year if year <= 68 else 1900 + year, int(text[2:4]), int(text[4:6])
    )
