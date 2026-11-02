"""Adapter for bankstatementparser's OFX/QFX implementation."""

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
from bankparser.models import Counterparty, Transaction
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.ofx.encoding import (
    _decode_ofx as _decode_ofx,  # noqa: PLC0414 -- keep the existing helper import path
)
from bankparser.parsers.ofx.source import read_source
from bankparser.parsers.scalars import (
    currency_text,
    is_missing_scalar,
)
from bankparser.parsers.scalars import (
    scalar_text as _text,
)

_SCOPE_PATTERN = re.compile(r"<(STMTRS|CCSTMTRS)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)


class BankStatementParserOfxAdapter:
    """Map bankstatementparser OFX/QFX output into the BankParser model."""

    id = "bankstatementparser"
    format = "ofx"

    def __init__(self) -> None:
        try:
            self._package = importlib.import_module("bankstatementparser")
            module = importlib.import_module("bankstatementparser.additional_parsers")
            self._parser_class = module.OfxParser
        except (ImportError, AttributeError) as exc:
            raise ParserDependencyError(
                "The 'bankstatementparser' package is required for OFX/QFX. "
                + dependency_install_hint("alternative")
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._package, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        evidence = read_source(data)
        canonical = evidence.canonical

        try:
            with TemporaryDirectory(prefix="bankparser-") as directory:
                suffix = Path(context.file_name or "").suffix.lower()
                if suffix not in {".ofx", ".qfx"}:
                    suffix = ".ofx"
                source = Path(directory) / f"statement{suffix}"
                source.write_bytes(evidence.backend_input)

                parser = self._parser_class(source)
                frame = parser.parse()
                summaries = parser.get_summaries()
                records = frame.to_dict("records")
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError("bankstatementparser OFX/QFX parser failed") from exc

        if len(records) != len(canonical.transactions):
            raise ParseError(
                "OFX source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
                location="BANKTRANLIST/STMTTRN",
            )
        if not summaries and not records:
            return canonical
        if len(summaries) != 1:
            raise ParseError(
                "OFX backend returned an unexpected account count",
                code="OFX_BACKEND_MISMATCH",
                location="OFX",
            )
        summary = summaries[0]
        if not isinstance(summary, Mapping):
            raise ParseError("bankstatementparser returned an invalid OFX summary")
        # Empty backend summaries carry no account/currency evidence.
        backend_account = _text(summary.get("account_id"))
        backend_currency = _currency(summary.get("currency"))
        if not records:
            backend_account = backend_account or canonical.account.id
            backend_currency = backend_currency or canonical.account.currency
        transactions = tuple(
            _map_transaction(record, statement_currency=canonical.account.currency)
            for record in records
        )
        if (
            backend_account != canonical.account.id
            or backend_currency != canonical.account.currency
            or _text(summary.get("opening_balance")) is not None
            or (
                not is_missing_scalar(summary.get("closing_balance"))
                and (
                    _optional_decimal(summary.get("closing_balance")) is None
                    or _optional_decimal(summary.get("closing_balance"))
                    != canonical.statement.closing_balance
                )
            )
            or any(
                actual.amount != expected.amount
                or actual.transaction_id != expected.transaction_id
                or actual.currency != expected.currency
                or actual.booking_date != expected.booking_date
                or (
                    _text(record.get("account_id")) is not None
                    and _text(record.get("account_id")) != canonical.account.id
                )
                for actual, expected, record in zip(
                    transactions, canonical.transactions, records
                )
            )
        ):
            raise ParseError(
                "OFX source and backend financial fields differ",
                code="OFX_BACKEND_MISMATCH",
                location="OFX",
            )
        return CanonicalData(
            canonical.account, canonical.statement, transactions, canonical.warnings
        )


def _map_transaction(
    record: Mapping[str, Any],
    *,
    statement_currency: str | None,
) -> Transaction:
    raw = {
        key: value
        for key, value in {
            "transaction_type": _text(record.get("transaction_type")),
        }.items()
        if value is not None
    }

    return Transaction(
        booking_date=_optional_ofx_date(record.get("date")),
        value_date=None,
        amount=_required_decimal(record.get("amount")),
        currency=_currency(record.get("currency")) or statement_currency,
        description=_text(record.get("description")),
        counterparty=Counterparty(),
        reference=None,
        transaction_id=_text(record.get("transaction_id")),
        raw=raw,
    )


def _single_statement_scope(text: str) -> str:
    scopes: list[str] = [body for _, body in _SCOPE_PATTERN.findall(text)]
    if len(scopes) != 1:
        raise ParseError(
            f"OFX/QFX contains {len(scopes)} statement scopes; "
            "BankParser currently expects exactly one",
            code="MULTIPLE_STATEMENTS",
            location="OFX/STMTRS or CCSTMTRS",
        )
    return scopes[0]


def _tag_value(source: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>\s*([^<\r\n]+)", source, flags=re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).strip() or None


def _container_tag_value(source: str, container: str, tag: str) -> str | None:
    match = re.search(
        rf"<{container}>(.*?)</{container}>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return None
    return _tag_value(match.group(1), tag)


def _required_decimal(value: Any) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ParseError("Parser returned an invalid amount")
    return parsed


def _optional_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if value is None:
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _optional_ofx_date(value: Any) -> date | None:
    if is_missing_scalar(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    compact = text[:8]
    if len(compact) != 8 or not compact.isdigit():
        raise ParseError("Parser returned an invalid OFX date")
    try:
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    except ValueError as exc:
        raise ParseError("Parser returned an invalid OFX date") from exc


def _currency(value: Any) -> str | None:
    return currency_text(value, location="OFX/currency")


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
