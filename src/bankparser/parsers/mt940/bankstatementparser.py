"""Adapter for the bankstatementparser MT940 implementation."""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.models import Account, Counterparty, Statement, Transaction, Warning
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.mt940.source import (
    balance_currency,
    source_fields,
)
from bankparser.parsers.scalars import is_missing_scalar
from bankparser.parsers.scalars import scalar_text as _text

_OPENING_DATE_PATTERN = re.compile(rb"(?m)^:60[FM]:[CD](\d{6})")
_CLOSING_DATE_PATTERN = re.compile(rb"(?m)^:62[FM]:[CD](\d{6})")


class BankStatementParserMt940Adapter:
    """Map bankstatementparser's MT940 output into the BankParser model."""

    id = "bankstatementparser"
    format = "mt940"

    def __init__(self) -> None:
        try:
            self._package = importlib.import_module("bankstatementparser")
            module = importlib.import_module("bankstatementparser.additional_parsers")
            self._parser_class = module.Mt940Parser
        except (ImportError, AttributeError) as exc:
            raise ParserDependencyError(
                "The 'bankstatementparser' package is required for the "
                "bankstatementparser implementation. "
                + dependency_install_hint("alternative")
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._package, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        fields, source_transactions = source_fields(data)
        try:
            with TemporaryDirectory(prefix="bankparser-") as directory:
                file_name = Path(context.file_name or "statement.mt940").name
                if not Path(file_name).suffix:
                    file_name += ".mt940"
                source = Path(directory) / file_name
                source.write_bytes(data)
                parser = self._parser_class(source)
                frame = parser.parse()
                summaries = parser.get_summaries()
                records = frame.to_dict("records")
        except Exception as exc:
            raise ParseError(f"bankstatementparser MT940 parser failed: {exc}") from exc

        if len(summaries) != 1:
            raise ParseError(
                "bankstatementparser returned "
                f"{len(summaries)} statement scopes; BankParser expects one",
                code="MULTIPLE_STATEMENTS",
            )
        summary = summaries[0]
        if not isinstance(summary, Mapping):
            raise ParseError(
                "bankstatementparser returned an invalid statement summary"
            )

        currency = _currency(summary.get("currency"))
        if len(source_transactions) != len(records):
            raise ParseError(
                "MT940 source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
            )
        transactions = tuple(
            _map_transaction(
                record, statement_currency=currency, source=source_transactions[index]
            )
            for index, record in enumerate(records)
        )
        if currency is None:
            transaction_currencies = {
                transaction.currency
                for transaction in transactions
                if transaction.currency is not None
            }
            if len(transaction_currencies) == 1:
                currency = next(iter(transaction_currencies))

        opening = _optional_decimal(summary.get("opening_balance"))
        closing = _optional_decimal(summary.get("closing_balance"))
        warnings: list[Warning] = []
        if currency is None:
            warnings.append(
                Warning("MISSING_CURRENCY", "Statement currency is unavailable")
            )
        if opening is None:
            warnings.append(
                Warning("MISSING_OPENING_BALANCE", "Opening balance is unavailable")
            )
        if closing is None:
            warnings.append(
                Warning("MISSING_CLOSING_BALANCE", "Closing balance is unavailable")
            )

        transaction_dates = [
            transaction.value_date
            for transaction in transactions
            if transaction.value_date is not None
        ]
        opening_date, closing_date = _statement_boundary_dates(data)
        summary_date = _optional_date(summary.get("statement_date"))
        statement_id, sequence = _statement_identity(summary.get("statement_id"))

        return CanonicalData(
            account=Account(
                id=_text(summary.get("account_id")), iban=None, currency=currency
            ),
            statement=Statement(
                id=statement_id,
                sequence=sequence,
                start_date=opening_date
                or (min(transaction_dates) if transaction_dates else None),
                end_date=closing_date
                or (max(transaction_dates) if transaction_dates else None)
                or summary_date,
                opening_balance=opening,
                closing_balance=closing,
                opening_balance_currency=balance_currency(fields, "60F"),
                closing_balance_currency=balance_currency(fields, "62F"),
            ),
            transactions=transactions,
            warnings=tuple(warnings),
        )


def _map_transaction(
    record: Mapping[str, Any],
    *,
    statement_currency: str | None,
    source: dict[str, object] | None = None,
) -> Transaction:
    value_date = _optional_date(record.get("date"))
    parser_transaction_id = _text(record.get("transaction_id"))
    raw: dict[str, Any] = (
        {"parser_transaction_id": parser_transaction_id}
        if parser_transaction_id is not None
        else {}
    )
    if source:
        raw.update(
            {
                key: value
                for key, value in source.items()
                if key != "booking_date" and value is not None
            }
        )

    return Transaction(
        booking_date=_optional_date(source.get("booking_date")) if source else None,
        value_date=value_date,
        amount=_required_decimal(record.get("amount")),
        currency=_currency(record.get("currency")) or statement_currency,
        description=_text(record.get("description")),
        counterparty=Counterparty(),
        reference=_text(source["customer_reference"] or source["bank_reference"])
        if source
        else None,
        transaction_id=None,
        raw=raw,
    )


def _statement_boundary_dates(data: bytes) -> tuple[date | None, date | None]:
    return (
        _mt940_date_from_match(_OPENING_DATE_PATTERN.search(data)),
        _mt940_date_from_match(_CLOSING_DATE_PATTERN.search(data)),
    )


def _mt940_date_from_match(match: re.Match[bytes] | None) -> date | None:
    if match is None:
        return None
    try:
        text = match.group(1).decode("ascii")
    except UnicodeDecodeError:
        return None
    year_two_digits = int(text[:2])
    year = 2000 + year_two_digits if year_two_digits <= 68 else 1900 + year_two_digits
    try:
        return date(year, int(text[2:4]), int(text[4:6]))
    except ValueError:
        return None


def _required_decimal(value: Any) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ParseError(f"Parser returned an invalid amount: {value!r}")
    return parsed


def _optional_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _optional_date(value: Any) -> date | None:
    if is_missing_scalar(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            pass
    raise ParseError(f"Parser returned an invalid date: {value!r}")


def _statement_identity(value: Any) -> tuple[str | None, str | None]:
    text = _text(value)
    if text is None:
        return None, None
    statement_id, separator, sequence = text.partition("/")
    return statement_id or None, (sequence or None) if separator else None


def _currency(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text is not None else None
