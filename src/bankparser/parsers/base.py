"""Minimal parser adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from bankparser.models import Account, Statement, Transaction, Warning
from bankparser.options import CsvOptions
from bankparser.profiles import CsvProfile


@dataclass(frozen=True, slots=True)
class ParseContext:
    """Metadata supplied to parser adapters."""

    file_name: str | None = None
    csv_options: CsvOptions | None = None
    csv_profile: CsvProfile | None = None


@dataclass(frozen=True, slots=True)
class CanonicalData:
    """Canonical data produced by an adapter before independent validation."""

    account: Account
    statement: Statement
    transactions: tuple[Transaction, ...]
    warnings: tuple[Warning, ...] = ()


class ParserAdapter(Protocol):
    """Interface implemented by every underlying parser adapter."""

    id: str
    format: str

    @property
    def implementation_version(self) -> str | None:
        """Return the underlying parser library version when available."""
        ...

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        """Parse bytes and map parser-native output to canonical data."""
        ...
