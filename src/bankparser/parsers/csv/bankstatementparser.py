"""Optional compatibility adapter for bankstatementparser CSV callers."""

from __future__ import annotations

import csv
import importlib
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.options import CsvOptions
from bankparser.parsers.base import CanonicalData, ParseContext

from .native import NativeCsvAdapter
from .source import read_layout


class BankStatementParserCsvAdapter:
    """Retain explicit backend selection and its transaction-count safeguard.

    Canonical fields use native source semantics. This adapter adds a backend
    count check; agreement is not an independent check of extracted fields.
    """

    id = "bankstatementparser"
    format = "csv"

    def __init__(self) -> None:
        try:
            self._package = importlib.import_module("bankstatementparser")
            module = importlib.import_module("bankstatementparser.additional_parsers")
            self._parser_class = module.CsvStatementParser
        except (ImportError, AttributeError) as exc:
            raise ParserDependencyError(
                "The 'bankstatementparser' package is required for explicit CSV "
                "backend selection. " + dependency_install_hint("alternative")
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._package, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        canonical = NativeCsvAdapter().parse(data, context)
        # Normalize only the backend count-check input, never the source raw cells.
        layout = read_layout(data, context.csv_options or CsvOptions())
        split = "amount" not in layout.columns
        headers = [
            "Booking Date",
            "Description",
            "Currency",
            "Account",
            "Reference",
        ] + (["Debit", "Credit"] if split else ["Amount"])
        try:
            with TemporaryDirectory(prefix="bankparser-") as directory:
                source = Path(directory) / "statement.csv"
                with source.open("w", encoding="utf-8", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=headers)
                    writer.writeheader()
                    for transaction in canonical.transactions:
                        row = {
                            "Booking Date": transaction.booking_date.isoformat()
                            if transaction.booking_date
                            else "",
                            "Description": transaction.description or "",
                            "Currency": transaction.currency or "",
                            "Account": canonical.account.id or "",
                            "Reference": transaction.reference or "",
                        }
                        if split:
                            row["Debit"] = str(
                                transaction.amount.copy_abs()
                                if transaction.amount < 0
                                else Decimal(0)
                            )
                            row["Credit"] = str(
                                transaction.amount
                                if transaction.amount > 0
                                else Decimal(0)
                            )
                        else:
                            row["Amount"] = str(transaction.amount)
                        writer.writerow(row)
                records = self._parser_class(source).parse().to_dict("records")
        except Exception as exc:
            raise ParseError(f"bankstatementparser CSV parser failed: {exc}") from exc
        if len(records) != len(canonical.transactions):
            raise ParseError(
                "CSV source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
            )
        return canonical
