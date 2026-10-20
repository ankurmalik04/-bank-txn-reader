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
from bankparser.models import Account, Counterparty, Statement, Transaction, Warning
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.ofx.encoding import (
    _decode_ofx as _decode_ofx,  # noqa: PLC0414 -- keep the existing helper import path
)
from bankparser.parsers.scalars import (
    is_missing_scalar,
    validate_amount_text,
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
        text = _decode_ofx(data)

        scope = _single_statement_scope(text)
        for match in re.finditer(
            r"<(TRNAMT|BALAMT)>\s*([^<\r\n]*)", scope, flags=re.IGNORECASE
        ):
            validate_amount_text(match[2], location=f"OFX/{match[1].upper()}")

        try:
            with TemporaryDirectory(prefix="bankparser-") as directory:
                suffix = Path(context.file_name or "").suffix.lower()
                if suffix not in {".ofx", ".qfx"}:
                    suffix = ".ofx"
                source = Path(directory) / f"statement{suffix}"
                source.write_bytes(text.encode("utf-8"))

                parser = self._parser_class(source)
                frame = parser.parse()
                summaries = parser.get_summaries()
                records = frame.to_dict("records")
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(
                f"bankstatementparser OFX/QFX parser failed: {exc}"
            ) from exc

        if len(summaries) != 1:
            raise ParseError(
                "bankstatementparser returned "
                f"{len(summaries)} OFX account/currency scopes; "
                "BankParser currently expects one"
            )

        summary = summaries[0]
        if not isinstance(summary, Mapping):
            raise ParseError("bankstatementparser returned an invalid OFX summary")

        currency = _first_not_none(
            _currency(summary.get("currency")),
            _currency(_tag_value(scope, "CURDEF")),
        )
        account_id = _first_not_none(
            _text(summary.get("account_id")),
            _text(_tag_value(scope, "ACCTID")),
        )

        transactions = tuple(
            _map_transaction(record, statement_currency=currency) for record in records
        )
        source_count = len(re.findall(r"<STMTTRN>", scope, flags=re.IGNORECASE))
        if source_count != len(transactions):
            raise ParseError(
                "OFX source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
                location="BANKTRANLIST/STMTTRN",
            )

        opening = _optional_decimal(summary.get("opening_balance"))
        closing = _first_not_none(
            _optional_decimal(summary.get("closing_balance")),
            _optional_decimal(_container_tag_value(scope, "LEDGERBAL", "BALAMT")),
        )

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

        start_date = _optional_ofx_date(_tag_value(scope, "DTSTART"))
        end_date = _first_not_none(
            _optional_ofx_date(_tag_value(scope, "DTEND")),
            _optional_ofx_date(_container_tag_value(scope, "LEDGERBAL", "DTASOF")),
        )

        return CanonicalData(
            account=Account(id=account_id, iban=None, currency=currency),
            statement=Statement(
                id=None,
                sequence=None,
                start_date=start_date,
                end_date=end_date,
                opening_balance=opening,
                closing_balance=closing,
                opening_balance_currency=currency if opening is not None else None,
                closing_balance_currency=currency if closing is not None else None,
            ),
            transactions=transactions,
            warnings=tuple(warnings),
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
        raise ParseError(f"Parser returned an invalid amount: {value!r}")
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
        raise ParseError(f"Parser returned an invalid OFX date: {value!r}")
    try:
        return date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
    except ValueError as exc:
        raise ParseError(f"Parser returned an invalid OFX date: {value!r}") from exc


def _currency(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text is not None else None


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
