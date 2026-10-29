"""Explicit, immutable conventions for CSV exports."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any

from bankparser.errors import InputError

CSV_FIELDS = frozenset(
    {
        "date",
        "booking_date",
        "value_date",
        "description",
        "amount",
        "debit",
        "credit",
        "balance",
        "currency",
        "account_id",
        "iban",
        "transaction_id",
        "reference",
    }
)
ENCODINGS = {
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "cp1252": "cp1252",
    "windows-1252": "cp1252",
    "latin-1": "iso-8859-1",
    "iso-8859-1": "iso-8859-1",
}


@dataclass(frozen=True, slots=True)
class CsvOptions:
    """CSV conventions; columns map exact stripped source headers to fields.

    Explicit columns replace synonyms. Amount is signed; Debit/Credit are
    non-negative magnitudes. Header positions are physical start lines.
    The original first three positional constructor arguments stay compatible.
    """

    decimal_separator: str | None = None
    grouping_separator: str | None = None
    date_format: str | None = None
    columns: Mapping[str, str] | None = None
    date_role: str | None = None
    default_currency: str | None = None
    expected_currency: str | None = None
    header_row: int | None = None
    header_search_limit: int | None = None
    encoding: str = "utf-8-sig"
    delimiter: str | None = None

    def __post_init__(self) -> None:
        if self.decimal_separator not in (None, ".", ","):
            raise InputError("CSV decimal_separator must be '.' or ','")
        if self.grouping_separator not in (None, ".", ",", " ", "'"):
            raise InputError("Unsupported CSV grouping_separator")
        if self.grouping_separator is not None and (
            self.decimal_separator is None
            or self.grouping_separator == self.decimal_separator
        ):
            raise InputError(
                "CSV grouping requires a distinct explicit decimal separator"
            )
        if self.date_format is not None and (
            not isinstance(self.date_format, str) or not self.date_format.strip()
        ):
            raise InputError("CSV date_format must be nonblank text")
        if self.columns is not None:
            if not isinstance(self.columns, Mapping) or not self.columns:
                raise InputError(
                    "CSV columns must be a nonempty source-header to field mapping"
                )
            copied = dict(self.columns)
            if any(
                not isinstance(k, str)
                or not k.strip()
                or k != k.strip()
                or not isinstance(v, str)
                or v not in CSV_FIELDS
                for k, v in copied.items()
            ):
                raise InputError(
                    "CSV mapping needs exact stripped source headers and known canonical targets"
                )
            if len(set(copied.values())) != len(copied):
                raise InputError("CSV mapping targets must be unique")
            targets = set(copied.values())
            if "amount" in targets and targets & {"debit", "credit"}:
                raise InputError("CSV mapping must choose Amount or Debit/Credit")
            object.__setattr__(self, "columns", MappingProxyType(copied))
        if self.date_role not in (None, "booking_date", "value_date"):
            raise InputError("CSV date_role must be booking_date or value_date")
        for name in ("default_currency", "expected_currency"):
            currency = getattr(self, name)
            if currency is not None:
                if (
                    not isinstance(currency, str)
                    or re.fullmatch(r"[A-Za-z]{3}", currency, re.ASCII) is None
                ):
                    raise InputError(f"CSV {name} must be a three-letter currency code")
                object.__setattr__(self, name, currency.upper())
        if (
            self.default_currency
            and self.expected_currency
            and self.default_currency != self.expected_currency
        ):
            raise InputError("CSV default_currency contradicts expected_currency")
        for name, maximum in (("header_row", 10000), ("header_search_limit", 200)):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not int or not 1 <= value <= maximum
            ):
                raise InputError(f"CSV {name} must be between 1 and {maximum}")
        if self.header_row is not None and self.header_search_limit is not None:
            raise InputError(
                "CSV header_row and header_search_limit are mutually exclusive"
            )
        if not isinstance(self.encoding, str) or self.encoding not in ENCODINGS:
            raise InputError("Unsupported explicit CSV encoding")
        object.__setattr__(self, "encoding", ENCODINGS[self.encoding])
        if self.delimiter not in (None, ",", ";", "\t", "|"):
            raise InputError("CSV delimiter must be comma, semicolon, tab or pipe")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe conventions without sharing a mutable mapping."""
        return {
            field.name: dict(self.columns)
            if field.name == "columns" and self.columns is not None
            else getattr(self, field.name)
            for field in fields(self)
        }
