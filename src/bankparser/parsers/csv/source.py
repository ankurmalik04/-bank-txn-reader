"""Bounded CSV header selection, explicit column meanings and physical locations."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass

from bankparser.detection.csv import CSV_COLUMN_GROUPS, normalize_csv_header
from bankparser.errors import ParseError
from bankparser.options import CsvOptions


@dataclass(frozen=True, slots=True)
class CsvLayout:
    text: str
    delimiter: str
    headers: tuple[str, ...]
    header_start: int
    header_end: int
    columns: dict[str, str]


def columns(
    headers: tuple[str, ...], options: CsvOptions | None = None
) -> dict[str, str]:
    options = options or CsvOptions()
    mapped: dict[str, str] = {}
    normalized = set()
    for header in headers:
        name = header if options.columns is not None else normalize_csv_header(header)
        if not name or name in normalized:
            raise ParseError(
                "CSV headers must be non-empty and unique",
                code="AMBIGUOUS_COLUMNS",
                location=f"CSV header {header!r}",
            )
        normalized.add(name)
        if options.columns is not None:
            logical = options.columns.get(header)
            if logical:
                mapped[logical] = header
        else:
            for logical, candidates in CSV_COLUMN_GROUPS.items():
                if name in candidates:
                    if logical in mapped:
                        raise ParseError(
                            f"Multiple CSV columns map to {logical}",
                            code="AMBIGUOUS_COLUMNS",
                            location=f"CSV header {header!r}",
                        )
                    mapped[logical] = header
    if options.columns is not None and set(options.columns) - set(headers):
        raise ParseError(
            "CSV mapping refers to missing source headers",
            code="MISSING_CSV_COLUMN",
            location="CSV header",
        )
    if options.date_role is not None and "date" in mapped:
        if options.date_role in mapped:
            raise ParseError(
                "Generic Date role duplicates an explicit date field",
                code="AMBIGUOUS_COLUMNS",
                location="CSV header",
            )
        mapped[options.date_role] = mapped.pop("date")
    return mapped


def _shape(mapped: dict[str, str]) -> bool:
    return bool(set(mapped) & {"amount", "debit", "credit"}) and bool(
        set(mapped)
        & {"date", "booking_date", "value_date", "description", "account_id", "iban"}
    )


def read_layout(data: bytes, options: CsvOptions) -> CsvLayout:
    try:
        text = data.decode(options.encoding)
    except UnicodeDecodeError as exc:
        raise ParseError("Invalid CSV encoding", code="INVALID_CSV") from exc
    candidates: list[tuple[int, CsvLayout]] = []
    errors: list[ParseError] = []
    for delimiter in (
        (options.delimiter,) if options.delimiter else (",", ";", "\t", "|")
    ):
        reader = csv.reader(
            io.StringIO(text, newline=""), delimiter=delimiter, strict=True
        )
        try:
            while True:
                start = reader.line_num + 1
                if (
                    options.header_search_limit is not None
                    and start > options.header_search_limit
                ):
                    break
                cells = next(reader)
                if (
                    options.header_search_limit is not None
                    and reader.line_num > options.header_search_limit
                ):
                    break
                if options.header_row is not None:
                    if start < options.header_row:
                        if reader.line_num >= options.header_row:
                            break
                        continue
                    if start > options.header_row:
                        break
                if not cells or not any(cell.strip() for cell in cells):
                    if options.header_row is not None:
                        break
                    continue
                headers = tuple(cell.strip() for cell in cells)
                if len(headers) >= 2:
                    try:
                        mapped = columns(headers, options)
                        if _shape(mapped):
                            layout = CsvLayout(
                                text, delimiter, headers, start, reader.line_num, mapped
                            )
                            candidates.append((len(mapped), layout))
                    except ParseError as exc:
                        errors.append(exc)
                if options.header_search_limit is None:
                    break
                if reader.line_num >= options.header_search_limit:
                    break
        except StopIteration:
            pass
        except csv.Error:
            errors.append(
                ParseError("Invalid CSV quoting or header", code="INVALID_CSV")
            )
    if not candidates:
        if errors:
            raise errors[0]
        raise ParseError(
            "No bank-shaped CSV header at the selected physical lines",
            code="INVALID_CSV_HEADER",
            location="CSV header",
        )
    if options.header_search_limit is not None and len(candidates) != 1:
        raise ParseError(
            "Multiple plausible CSV headers in search window; select header_row",
            code="AMBIGUOUS_CSV_HEADER",
            location="CSV header",
        )
    layout = max(candidates, key=lambda item: item[0])[1]
    mapped = layout.columns
    if "amount" in mapped and set(mapped) & {"debit", "credit"}:
        raise ParseError(
            "Choose Amount or Debit/Credit columns, not both",
            code="AMBIGUOUS_COLUMNS",
            location="CSV header",
        )
    return layout


def source_rows(layout: CsvLayout) -> Iterator[tuple[int, int, dict[str, str]]]:
    reader = csv.reader(
        io.StringIO(layout.text, newline=""), delimiter=layout.delimiter, strict=True
    )
    try:
        while reader.line_num < layout.header_end:
            next(reader)
        while True:
            start = reader.line_num + 1
            cells = next(reader)
            if not cells or not any(cell.strip() for cell in cells):
                continue
            if len(cells) != len(layout.headers):
                raise ParseError(
                    f"Expected {len(layout.headers)} CSV cells, received {len(cells)}",
                    code="INVALID_CSV_ROW",
                    location=f"CSV line {reader.line_num}",
                )
            yield start, reader.line_num, dict(zip(layout.headers, cells))
    except StopIteration:
        return
    except csv.Error as exc:
        raise ParseError("Invalid CSV quoting or encoding", code="INVALID_CSV") from exc
