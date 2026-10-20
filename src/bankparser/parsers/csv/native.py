"""Native CSV parsing using only the Python standard library."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal

from bankparser.detection.csv import CSV_COLUMN_GROUPS, csv_header, normalize_csv_header
from bankparser.errors import ParseError
from bankparser.models import Account, Statement, Transaction, Warning
from bankparser.options import CsvOptions
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.version import __version__


class NativeCsvAdapter:
    """Map validated CSV cells directly into the canonical model."""

    id = "native"
    format = "csv"

    @property
    def implementation_version(self) -> str:
        return __version__

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        options = context.csv_options or CsvOptions()
        headers, rows = _read_source(data)
        columns = _columns(headers)
        if "amount" in columns and ("debit" in columns or "credit" in columns):
            raise ParseError(
                "Choose Amount or Debit/Credit columns, not both",
                code="AMBIGUOUS_COLUMNS",
                location="CSV header",
            )
        if not any(name in columns for name in ("amount", "debit", "credit")):
            raise ParseError(
                "CSV requires Amount or Debit/Credit columns",
                code="MISSING_AMOUNT",
                location="CSV header",
            )
        transactions = []
        warnings = {
            warning.code: warning
            for warning in (
                Warning(
                    "MISSING_OPENING_BALANCE",
                    "Opening balance is unavailable with generic CSV semantics",
                ),
                Warning(
                    "MISSING_CLOSING_BALANCE",
                    "Closing balance is unavailable with generic CSV semantics",
                ),
            )
        }
        scope: tuple[str | None, str | None] | None = None
        start_date: date | None = None
        end_date: date | None = None
        for line, row in rows:

            def cell(name: str, row: dict[str, str] = row) -> str:
                return row.get(columns.get(name, ""), "").strip()

            currency = cell("currency").upper() or None
            account_id = cell("account_id") or None
            row_scope = (account_id, currency)
            if scope is None:
                scope = row_scope
            elif scope != row_scope:
                raise ParseError(
                    "CSV contains multiple account/currency scopes; supply one scope per file",
                    code="MULTIPLE_STATEMENTS",
                    location="CSV account/currency columns",
                )
            if "amount" in columns:
                amount = _amount(cell("amount"), options, line, columns["amount"])
            else:
                movements = {}
                for name in ("debit", "credit"):
                    movements[name] = (
                        _amount(cell(name), options, line, columns[name])
                        if cell(name)
                        else Decimal(0)
                    )
                    if movements[name] < 0:
                        raise ParseError(
                            "Debit/Credit cells must be non-negative magnitudes; use a signed Amount column",
                            code="SIGNED_DEBIT_CREDIT",
                            location=f"CSV line {line}, column {columns[name]!r}",
                        )
                if not cell("debit") and not cell("credit"):
                    raise ParseError(
                        "Transaction has no amount",
                        code="MISSING_AMOUNT",
                        location=f"CSV line {line}",
                    )
                if movements["debit"] and movements["credit"]:
                    raise ParseError(
                        "Both Debit and Credit are non-zero",
                        code="AMBIGUOUS_MOVEMENT",
                        location=f"CSV line {line}",
                    )
                amount = (
                    movements["credit"]
                    if movements["credit"]
                    else movements["debit"].copy_negate()
                )

            parsed_dates = {}
            for name in ("booking_date", "value_date", "date"):
                text = cell(name)
                parsed = _optional_csv_date(text, options.date_format)
                parsed_dates[name] = parsed
                if parsed:
                    start_date = min(start_date, parsed) if start_date else parsed
                    end_date = max(end_date, parsed) if end_date else parsed
                if text and parsed is None:
                    warnings.setdefault(
                        "UNPARSED_TRANSACTION_DATE",
                        Warning(
                            "UNPARSED_TRANSACTION_DATE",
                            "Date is invalid or ambiguous; set CsvOptions.date_format",
                            f"CSV line {line}, column {columns[name]!r}",
                        ),
                    )
            if cell("date"):
                warnings.setdefault(
                    "AMBIGUOUS_DATE_SEMANTICS",
                    Warning(
                        "AMBIGUOUS_DATE_SEMANTICS",
                        "Generic Date is preserved but is not a booking or value date",
                        f"CSV line {line}, column {columns['date']!r}",
                    ),
                )
            if cell("balance"):
                warnings.setdefault(
                    "CSV_BALANCE_ORDER_UNKNOWN",
                    Warning(
                        "CSV_BALANCE_ORDER_UNKNOWN",
                        "Running balance is preserved; its ordering and timing are unknown",
                        f"CSV line {line}, column {columns['balance']!r}",
                    ),
                )
            raw = {"source_line": line, "source_fields": row}
            if cell("date"):
                raw["source_date"] = cell("date")
            if cell("balance"):
                raw["source_balance"] = cell("balance")
            transactions.append(
                Transaction(
                    booking_date=parsed_dates["booking_date"],
                    value_date=parsed_dates["value_date"],
                    amount=amount,
                    currency=currency,
                    description=cell("description") or None,
                    reference=cell("reference") or None,
                    transaction_id=cell("transaction_id") or None,
                    raw=raw,
                )
            )

        if not transactions:
            raise ParseError(
                "CSV contains no transactions",
                code="EMPTY_STATEMENT",
                location="CSV header",
            )
        account_id, currency = scope or (None, None)
        if currency is None:
            warnings["MISSING_CURRENCY"] = Warning(
                "MISSING_CURRENCY", "Statement currency is unavailable"
            )

        return CanonicalData(
            account=Account(
                id=account_id,
                iban=account_id
                if normalize_csv_header(columns.get("account_id", "")) == "iban"
                else None,
                currency=currency,
            ),
            statement=Statement(
                start_date=start_date,
                end_date=end_date,
            ),
            transactions=tuple(transactions),
            warnings=tuple(warnings.values()),
        )


def _read_source(
    data: bytes,
) -> tuple[tuple[str, ...], Iterator[tuple[int, dict[str, str]]]]:
    detected = csv_header(data)
    if detected is None:
        raise ParseError(
            "CSV must have recognizable headers and UTF-8 encoding",
            code="INVALID_CSV",
            location="CSV header",
        )
    delimiter, headers = detected
    return headers, _source_rows(data, delimiter, headers)


def _source_rows(
    data: bytes, delimiter: str, headers: tuple[str, ...]
) -> Iterator[tuple[int, dict[str, str]]]:
    try:
        with io.TextIOWrapper(
            io.BytesIO(data), encoding="utf-8-sig", newline=""
        ) as source:
            reader = csv.reader(source, delimiter=delimiter, strict=True)
            for cells in reader:
                if cells and any(cell.strip() for cell in cells):
                    break
            for cells in reader:
                if not cells or not any(cell.strip() for cell in cells):
                    continue
                if len(cells) != len(headers):
                    raise ParseError(
                        f"Expected {len(headers)} CSV cells, received {len(cells)}",
                        code="INVALID_CSV_ROW",
                        location=f"CSV line {reader.line_num}",
                    )
                yield reader.line_num, dict(zip(headers, cells))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ParseError("Invalid CSV quoting or encoding", code="INVALID_CSV") from exc


def _columns(headers: tuple[str, ...]) -> dict[str, str]:
    mapped = {}
    normalized = set()
    for header in headers:
        name = normalize_csv_header(header)
        if not name or name in normalized:
            raise ParseError(
                "CSV headers must be non-empty and unique",
                code="AMBIGUOUS_COLUMNS",
                location=f"CSV header {header!r}",
            )
        normalized.add(name)
        for logical, candidates in CSV_COLUMN_GROUPS.items():
            if name in candidates:
                if logical in mapped:
                    raise ParseError(
                        f"Multiple CSV columns map to {logical}",
                        code="AMBIGUOUS_COLUMNS",
                        location=f"CSV header {header!r}",
                    )
                mapped[logical] = header
    return mapped


def _amount(text: str, options: CsvOptions, line: int, column: str) -> Decimal:
    location = f"CSV line {line}, column {column!r}"
    decimal, grouping = options.decimal_separator, options.grouping_separator
    if decimal is None:
        separators = [separator for separator in (".", ",") if separator in text]
        if len(separators) > 1 or (
            separators
            and (
                text.count(separators[0]) > 1
                or len(text.rsplit(separators[0], 1)[1]) == 3
            )
        ):
            raise ParseError(
                "Ambiguous monetary separators; set CsvOptions explicitly",
                code="AMBIGUOUS_AMOUNT",
                location=location,
            )
        decimal = separators[0] if separators else "."
    integer, separator, fraction = text.partition(decimal)
    if grouping and grouping in integer:
        chunks = integer.lstrip("+-").split(grouping)
        if not (
            1 <= len(chunks[0]) <= 3
            and chunks[0].isdigit()
            and all(len(chunk) == 3 and chunk.isdigit() for chunk in chunks[1:])
        ):
            raise ParseError(
                "Invalid thousands grouping", code="INVALID_AMOUNT", location=location
            )
        integer = integer.replace(grouping, "")
    if not re.fullmatch(r"[+-]?\d*", integer, flags=re.ASCII):
        raise ParseError(
            "Unexpected separator for the selected CSV conventions",
            code="INVALID_AMOUNT",
            location=location,
        )
    normalized = integer + ("." + fraction if separator else "")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", normalized, flags=re.ASCII):
        raise ParseError(
            "Invalid amount for the selected CSV conventions",
            code="INVALID_AMOUNT",
            location=location,
        )
    return Decimal(normalized)


def _optional_csv_date(text: str, date_format: str | None = None) -> date | None:
    if not text:
        return None
    if date_format:
        try:
            return (
                datetime.strptime(text, date_format).replace(tzinfo=timezone.utc).date()
            )
        except ValueError:
            return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    slash = text.split("/")
    if len(slash) == 3 and len(slash[0]) == 4:
        return _date_from_parts(slash[0], slash[1], slash[2])
    dot = text.split(".")
    if len(dot) == 3:
        return _date_from_parts(dot[2], dot[1], dot[0])
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if not match:
        return None
    first, second, year = map(int, match.groups())
    if first > 12 and second <= 12:
        day, month = first, second
    elif second > 12 and first <= 12:
        month, day = first, second
    else:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_from_parts(year: str, month: str, day: str) -> date | None:
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return None
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None
