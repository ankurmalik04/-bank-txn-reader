"""Optional compatibility adapter for bankstatementparser CSV callers."""

from __future__ import annotations

import csv
import importlib
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from bankparser.detection.csv import csv_header
from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.parsers.base import CanonicalData, ParseContext

from .native import NativeCsvAdapter, _columns


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
                "backend selection. "
                + dependency_install_hint("alternative")
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._package, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        canonical = NativeCsvAdapter().parse(data, context)
        # Native parsing has already validated the header and every source row.
        detected = csv_header(data)
        assert detected is not None
        delimiter, headers = detected
        columns = _columns(headers)
        try:
            with TemporaryDirectory(prefix="bankparser-") as directory:
                source = Path(directory) / "statement.csv"
                with source.open("w", encoding="utf-8", newline="") as output:
                    writer = csv.DictWriter(
                        output, fieldnames=headers, delimiter=delimiter
                    )
                    writer.writeheader()
                    for transaction in canonical.transactions:
                        row = dict(transaction.raw["source_fields"])
                        if "amount" in columns:
                            row[columns["amount"]] = str(transaction.amount)
                        else:
                            for name in ("debit", "credit"):
                                if name in columns and row[columns[name]].strip():
                                    active = (
                                        name == "debit" and transaction.amount < 0
                                    ) or (name == "credit" and transaction.amount > 0)
                                    row[columns[name]] = str(
                                        transaction.amount.copy_abs()
                                        if active
                                        else Decimal(0)
                                    )
                        if "balance" in columns:
                            row[columns["balance"]] = ""
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
