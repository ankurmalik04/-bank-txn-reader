"""Stable canonical BankParser models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

ValidationStatus = Literal["passed", "warning", "failed"]
CheckStatus = Literal["passed", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class Counterparty:
    """Canonical counterparty information when present in the source."""

    name: str | None = None
    account_id: str | None = None
    iban: str | None = None


@dataclass(frozen=True, slots=True)
class Transaction:
    """One canonical account movement.

    Amount follows the BankParser convention: incoming money is positive and
    outgoing money is negative.
    """

    booking_date: date | None
    value_date: date | None
    amount: Decimal
    currency: str | None
    description: str | None = None
    counterparty: Counterparty = field(default_factory=Counterparty)
    reference: str | None = None
    transaction_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Account:
    """Canonical account metadata."""

    id: str | None = None
    iban: str | None = None
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class Statement:
    """Canonical statement-level metadata."""

    id: str | None = None
    sequence: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    opening_balance_currency: str | None = None
    closing_balance_currency: str | None = None


@dataclass(frozen=True, slots=True)
class Warning:
    """Machine-readable non-fatal parse warning."""

    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    """One independent validation check."""

    code: str
    status: CheckStatus
    message: str
    expected: str | None = None
    actual: str | None = None
    record_indices: tuple[int, ...] = field(
        default=(), metadata={"diagnostic_only": True}
    )
    source_locations: tuple[str | None, ...] = field(
        default=(), metadata={"diagnostic_only": True}
    )
    canonical_field: str | None = field(
        default=None, metadata={"diagnostic_only": True}
    )
    guidance: str | None = field(default=None, metadata={"diagnostic_only": True})

    @property
    def severity(self) -> str:
        """Map the existing validation status to a stable diagnostic severity."""
        return {"passed": "info", "skipped": "warning", "failed": "error"}[self.status]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Aggregate validation result returned with every parse."""

    status: ValidationStatus
    checks: tuple[ValidationCheck, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Provenance describing how a result was produced."""

    format: str
    implementation: str
    implementation_version: str | None
    bankparser_version: str
    file_name: str | None = None


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Stable top-level BankParser return type."""

    schema_version: str
    source: SourceMetadata
    account: Account
    statement: Statement
    transactions: tuple[Transaction, ...]
    validation: ValidationResult
    warnings: tuple[Warning, ...] = ()
