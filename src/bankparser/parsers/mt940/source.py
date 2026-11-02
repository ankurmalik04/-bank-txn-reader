"""Source-level safeguards shared by both MT940 adapters."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from bankparser.errors import ParseError
from bankparser.models import Account, Statement, Transaction
from bankparser.parsers.scalars import currency_text, scalar_text

_TAGS = re.compile(rb"(?m)^(?:\xef\xbb\xbf)?:(20|25|28C|60[FM]|61|62[FM]):([^\r\n]*)")
_TRANSACTION = re.compile(
    r"(?P<date>\d{6})(?P<entry_date>\d{4})?(?P<mark>RC|RD|EC|ED|C|D)"
    r"[A-Z]?(?P<amount>[0-9]+(?:,[0-9]*)?)(?P<code>[A-Z][A-Z0-9]{3})(?P<reference>.*)",
    re.IGNORECASE | re.ASCII,
)


def source_fields(data: bytes) -> tuple[dict[str, str], list[dict[str, object]]]:
    """Reject multiple scopes and retain fields discarded by native parsers.

    Retain exact signed financial evidence independently of backend arithmetic.
    References are scoped evidence, not guaranteed unique transaction IDs.
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
                "value_date": value_date,
                "amount": _signed_amount(parsed["amount"], parsed["mark"]),
                "mark": parsed["mark"].upper(),
                "backend_reference": parsed["code"] + parsed["reference"],
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
    currency = balance_currency(fields, "60F") or balance_currency(fields, "62F")
    for transaction in transactions:
        transaction["currency"] = currency
    return fields, transactions


def balance_currency(fields: dict[str, str], tag: str) -> str | None:
    balance = _source_balance(fields, tag)
    return balance[1] if balance is not None else None


def _signed_amount(text: str, mark: str) -> Decimal:
    value = Decimal(text.replace(",", "."))
    return value.copy_negate() if mark.upper() in {"D", "RC", "ED"} else value


def _source_balance(fields: dict[str, str], tag: str) -> tuple[Decimal, str] | None:
    text = fields.get(tag)
    if text is None:
        return None
    match = re.fullmatch(r"([CD])([0-9]{6})(.{3})([0-9]+(?:,[0-9]*)?)", text)
    if match is None:
        raise ParseError(
            "Unsupported MT940 balance structure",
            code="UNSUPPORTED_TRANSACTION",
            location=f":{tag}:",
        )
    currency = currency_text(match[3], location=f":{tag}:/currency")
    assert currency is not None
    return _signed_amount(match[4], match[1]), currency


def verify_transaction(
    source: dict[str, object], transaction: Transaction, *, backend: str
) -> None:
    """Reject financial misalignment before attaching any source metadata."""
    mismatch = (
        transaction.amount != source["amount"]
        or transaction.value_date != source["value_date"]
        or (
            source["currency"] is not None
            and transaction.currency != source["currency"]
        )
    )
    if backend == "wolph":
        mismatch = (
            mismatch
            or transaction.booking_date != source["booking_date"]
            or any(
                scalar_text(transaction.raw.get(key)) != source[key]
                for key in ("customer_reference", "bank_reference")
            )
        )
    else:
        mismatch = (
            mismatch
            or transaction.raw.get("parser_transaction_id")
            != source["backend_reference"]
        )
    if mismatch:
        raise ParseError(
            "MT940 source and backend transaction fields differ",
            code="TRANSACTION_ALIGNMENT_MISMATCH",
            location=f"line {source['source_line']} :61:",
            canonical_field="transactions",
        )


def verify_statement(
    fields: dict[str, str], account: Account, statement: Statement
) -> None:
    """Check source account, currency and final balances against backend output."""
    mismatch = account.id != (fields.get("25") or None)
    currency = balance_currency(fields, "60F") or balance_currency(fields, "62F")
    if currency is not None and account.currency != currency:
        mismatch = True
    for tag, key in (("60F", "opening_balance"), ("62F", "closing_balance")):
        expected = _source_balance(fields, tag)
        if getattr(statement, key) != (expected[0] if expected else None) or getattr(
            statement, key + "_currency"
        ) != (expected[1] if expected else None):
            mismatch = True
    if mismatch:
        raise ParseError(
            "MT940 source and backend statement fields differ",
            code="TRANSACTION_ALIGNMENT_MISMATCH",
            location="MT940/statement",
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
