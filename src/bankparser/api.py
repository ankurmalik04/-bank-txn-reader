"""Small public parsing API."""

from __future__ import annotations

from decimal import MAX_EMAX, MIN_EMIN, Context, localcontext
from functools import lru_cache
from os import PathLike

from bankparser._input import csv_configuration, input_format, load_input
from bankparser.errors import BankParserError
from bankparser.models import ParseResult, SourceMetadata, Warning
from bankparser.options import CsvOptions
from bankparser.parsers.base import ParseContext
from bankparser.parsers.camt053 import BankStatementParserCamt053Adapter
from bankparser.parsers.csv import BankStatementParserCsvAdapter, NativeCsvAdapter
from bankparser.parsers.mt940 import (
    BankStatementParserMt940Adapter,
    WolphMt940Adapter,
)
from bankparser.parsers.ofx import BankStatementParserOfxAdapter, OfxParseAdapter
from bankparser.parsers.registry import ParserRegistry
from bankparser.parsers.selector import select_parser
from bankparser.profiles import CsvProfile
from bankparser.validation import validate
from bankparser.version import __version__

SCHEMA_VERSION = "1.1"
# Authoritative input limit, also used by comparison's initial snapshot.
MAX_INPUT_BYTES = 5 * 1024 * 1024


def parse(
    source: str | PathLike[str] | bytes,
    *,
    implementation: str | None = None,
    csv_options: CsvOptions | None = None,
    csv_profile: CsvProfile | None = None,
    format: str | None = None,
) -> ParseResult:
    """Parse a supported bank statement into the canonical BankParser model."""
    data, file_name = load_input(source, max_bytes=MAX_INPUT_BYTES)
    csv_options = csv_configuration(csv_options, csv_profile)
    format = input_format(data, csv_options=csv_options, format=format)
    try:
        adapter = select_parser(
            _default_registry(), format=format, implementation=implementation
        )
    except BankParserError as exc:
        if exc.format is None:
            exc.format = format
        raise
    # Backends perform signed Decimal arithmetic. Isolate it from callers'
    # precision, exponent limits and traps; input length bounds literal digits
    # and provides room for carries when the backend totals source movements.
    with localcontext(Context(prec=max(28, len(data)), Emin=MIN_EMIN, Emax=MAX_EMAX)):
        try:
            canonical = adapter.parse(
                data,
                ParseContext(
                    file_name=file_name,
                    csv_options=csv_options,
                    csv_profile=csv_profile,
                ),
            )
        except BankParserError as exc:
            if exc.format is None:
                exc.format = format
            raise
    validation = validate(
        canonical.account, canonical.statement, canonical.transactions
    )
    warnings = canonical.warnings
    if any(
        check.code == "ACCOUNT_IDENTITY" and check.status == "skipped"
        for check in validation.checks
    ):
        warnings += (
            Warning(
                "MISSING_ACCOUNT_IDENTITY",
                "Account identity is unavailable; select and verify the destination account",
                "account",
            ),
        )

    return ParseResult(
        schema_version=SCHEMA_VERSION,
        source=SourceMetadata(
            format=format,
            implementation=adapter.id,
            implementation_version=adapter.implementation_version,
            bankparser_version=__version__,
            file_name=file_name,
        ),
        account=canonical.account,
        statement=canonical.statement,
        transactions=canonical.transactions,
        validation=validation,
        warnings=warnings,
    )


def implementations(format: str) -> tuple[str, ...]:
    """List configured implementations for a supported format."""
    return _default_registry().implementations(format)


@lru_cache(maxsize=1)
def _default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(
        format="mt940",
        implementation="wolph",
        factory=WolphMt940Adapter,
        default=True,
    )
    registry.register(
        format="mt940",
        implementation="bankstatementparser",
        factory=BankStatementParserMt940Adapter,
    )
    registry.register(
        format="camt053",
        implementation="bankstatementparser",
        factory=BankStatementParserCamt053Adapter,
        default=True,
    )
    registry.register(
        format="ofx",
        implementation="ofxparse",
        factory=OfxParseAdapter,
        default=True,
    )
    registry.register(
        format="ofx",
        implementation="bankstatementparser",
        factory=BankStatementParserOfxAdapter,
    )
    registry.register(
        format="csv",
        implementation="bankstatementparser",
        factory=BankStatementParserCsvAdapter,
    )
    registry.register(
        format="csv",
        implementation="native",
        factory=NativeCsvAdapter,
        default=True,
    )
    return registry
