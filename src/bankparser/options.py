"""Explicit conventions for CSV exports that cannot be inferred safely."""

from dataclasses import dataclass

from bankparser.errors import InputError


@dataclass(frozen=True, slots=True)
class CsvOptions:
    """Amount separators and optional ``strptime`` date format.

    Without options, only unambiguous ungrouped amounts and dates are accepted.
    Debit and credit columns always contain non-negative magnitudes.
    """

    decimal_separator: str | None = None
    grouping_separator: str | None = None
    date_format: str | None = None

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
