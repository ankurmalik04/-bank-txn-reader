"""Guarded, in-memory adapter for the MIT-licensed ofxparse backend."""

from __future__ import annotations

import importlib
from importlib.metadata import version
from io import BytesIO
from threading import Lock
from typing import Any

from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.models import Warning
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.ofx.source import read_source

# ofxparse 0.21 stores parse options on its class. Serialize our invocations.
_BACKEND_LOCK = Lock()


class OfxParseAdapter:
    id = "ofxparse"
    format = "ofx"

    def __init__(self) -> None:
        try:
            self._parser = importlib.import_module("ofxparse").OfxParser
            importlib.import_module("defusedxml.ElementTree")
        except (ImportError, AttributeError) as exc:
            raise ParserDependencyError(
                "The ofxparse implementation requires the OFX dependencies. "
                + dependency_install_hint("ofx")
            ) from exc

    @property
    def implementation_version(self) -> str:
        return version("ofxparse")

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        source = read_source(data)
        try:
            with _BACKEND_LOCK:
                parsed = self._parser.parse(
                    BytesIO(source.backend_input),
                    fail_fast=True,
                    custom_date_format=None,
                )
            return _map_checked(parsed, source.canonical)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError(
                "ofxparse failed to parse the validated statement",
                code="OFX_BACKEND_ERROR",
                location="OFX",
            ) from exc


def _map_checked(parsed: Any, canonical: CanonicalData) -> CanonicalData:
    if len(parsed.accounts) != 1:
        raise ParseError(
            "ofxparse returned an unexpected account count",
            code="OFX_BACKEND_MISMATCH",
            location="OFX",
        )
    account = parsed.accounts[0]
    statement = account.statement
    if statement.discarded_entries:
        raise ParseError(
            "ofxparse discarded transaction entries",
            code="INCOMPLETE_OUTPUT",
            location="BANKTRANLIST",
        )
    if len(statement.transactions) != len(canonical.transactions):
        raise ParseError(
            "OFX source and backend transaction counts differ",
            code="TRANSACTION_COUNT_MISMATCH",
            location="BANKTRANLIST/STMTTRN",
        )
    if (
        (account.account_id or None) != canonical.account.id
        or (statement.currency.upper() or None) != canonical.account.currency
        or getattr(statement, "balance", None) != canonical.statement.closing_balance
        or any(
            tx.id != expected.transaction_id or tx.amount != expected.amount
            for tx, expected in zip(statement.transactions, canonical.transactions)
        )
    ):
        raise ParseError(
            "OFX source and backend financial fields differ",
            code="OFX_BACKEND_MISMATCH",
            location="OFX",
        )
    warnings = canonical.warnings + tuple(
        Warning("OFX_BACKEND_WARNING", str(message), "OFX")
        for message in (*account.warnings, *statement.warnings)
    )
    return CanonicalData(
        canonical.account, canonical.statement, canonical.transactions, warnings
    )
