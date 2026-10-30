"""Small public parsing API."""

from __future__ import annotations

from decimal import MAX_EMAX, MIN_EMIN, Context, localcontext
from functools import lru_cache
from os import PathLike
from pathlib import Path

from bankparser.detection import detect_format
from bankparser.errors import InputError, UnsupportedFormatError
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
    data, file_name = _load_input(source)
    csv_options = _csv_configuration(csv_options, csv_profile)
    format = _input_format(data, csv_options=csv_options, format=format)
    adapter = select_parser(
        _default_registry(), format=format, implementation=implementation
    )
    # Backends perform signed Decimal arithmetic. Isolate it from callers'
    # precision, exponent limits and traps; input length bounds literal digits
    # and provides room for carries when the backend totals source movements.
    with localcontext(Context(prec=max(28, len(data)), Emin=MIN_EMIN, Emax=MAX_EMAX)):
        canonical = adapter.parse(
            data,
            ParseContext(
                file_name=file_name, csv_options=csv_options, csv_profile=csv_profile
            ),
        )
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


def _csv_configuration(
    options: CsvOptions | None, profile: CsvProfile | None
) -> CsvOptions | None:
    if profile is not None:
        if not isinstance(profile, CsvProfile) or options is not None:
            raise InputError("Supply csv_profile or csv_options, not both")
        return profile.options
    if options is not None and not isinstance(options, CsvOptions):
        raise InputError("csv_options must be CsvOptions")
    return options


def _input_format(
    data: bytes, *, csv_options: CsvOptions | None, format: str | None
) -> str:
    if format not in (None, "csv"):
        raise InputError("Only format='csv' is supported as an explicit override")
    try:
        detected = detect_format(data)
    except UnsupportedFormatError:
        if format == "csv" or csv_options is not None:
            return (
                "csv"  # The adapter must still validate header shape, rows and amounts.
            )
        raise
    if detected != "csv" and (csv_options is not None or format == "csv"):
        raise InputError(
            "csv_options/CSV format override can only be used with CSV input"
        )
    return detected


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


def _load_input(source: str | PathLike[str] | bytes) -> tuple[bytes, str | None]:
    if isinstance(source, bytes):
        data = source
        file_name = None
    else:
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise InputError(f"Unable to read input file {path}: {exc}") from exc
        if size > MAX_INPUT_BYTES:
            raise InputError(
                f"Input is too large ({size} bytes); maximum is {MAX_INPUT_BYTES} bytes"
            )
        try:
            with path.open("rb") as source_file:
                data = source_file.read(MAX_INPUT_BYTES + 1)
        except OSError as exc:
            raise InputError(f"Unable to read input file {path}: {exc}") from exc
        file_name = path.name

    if not data:
        raise InputError("Input file is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise InputError(
            f"Input is too large ({len(data)} bytes); maximum is {MAX_INPUT_BYTES} bytes"
        )
    return data, file_name
