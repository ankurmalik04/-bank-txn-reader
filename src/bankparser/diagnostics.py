"""Structured, actionable diagnostics derived from parse and error results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from bankparser.errors import BankParserError
from bankparser.models import ParseResult

Severity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One structured issue; transaction indices are zero-based."""

    diagnostic_schema_version: Literal["1"]
    code: str
    severity: Severity
    message: str
    format: str | None = None
    record_indices: tuple[int, ...] = ()
    source_locations: tuple[str | None, ...] = ()
    canonical_field: str | None = None
    guidance: str | None = None
    expected: str | None = None
    actual: str | None = None


_FIELD_BY_CODE = {
    "ACCOUNT_IDENTITY": "account.id",
    "BALANCE_RECONCILIATION": "statement.closing_balance",
    "INVALID_CSV": "transactions",
    "INVALID_STATEMENT_DATE": "statement.start_date",
    "MISSING_AMOUNT": "transactions.amount",
    "TRANSACTION_ALIGNMENT_MISMATCH": "transactions",
    "AMBIGUOUS_TRANSACTION_ALIGNMENT": "transactions",
    "CURRENCY_CONSISTENCY": "transactions.currency",
    "MISSING_ACCOUNT_IDENTITY": "account.id",
    "MISSING_CURRENCY": "account.currency",
    "MISSING_OPENING_BALANCE": "statement.opening_balance",
    "MISSING_CLOSING_BALANCE": "statement.closing_balance",
    "TRANSACTION_BOOKING_DATES": "transactions.booking_date",
    "TRANSACTION_CURRENCIES": "transactions.currency",
    "TRANSACTION_VALUE_DATES": "transactions.value_date",
}

_GUIDANCE_BY_CODE = {
    "ACCOUNT_IDENTITY": "Select the intended destination account and verify its mapping.",
    "BALANCE_RECONCILIATION": "Check the statement balances, booked movements, and account scope.",
    "INVALID_CSV": "Check the CSV encoding, delimiter, header, quoting, and row structure.",
    "INVALID_STATEMENT_DATE": "Correct the statement date value or its source format.",
    "MISSING_AMOUNT": "Provide one unambiguous booked amount for the transaction.",
    "TRANSACTION_ALIGNMENT_MISMATCH": "Check that source records and parser output preserve the same order and financial fields.",
    "AMBIGUOUS_TRANSACTION_ALIGNMENT": "Provide distinguishing source references or resolve the repeated records before import.",
    "CURRENCY_CONSISTENCY": "Check the account, balance, and transaction currencies in the statement.",
    "MISSING_ACCOUNT_IDENTITY": "Select and verify the destination account before importing.",
    "MISSING_CURRENCY": "Confirm the account or transaction currency from the source statement.",
    "MISSING_OPENING_BALANCE": "Provide the opening balance when the statement supplies one.",
    "MISSING_CLOSING_BALANCE": "Provide the closing balance when the statement supplies one.",
    "TRANSACTION_BOOKING_DATES": "Supply a valid booking date for each affected transaction.",
    "TRANSACTION_CURRENCIES": "Supply a currency for each affected transaction.",
    "TRANSACTION_VALUE_DATES": "Supply a valid value date when the source provides one.",
}


def diagnostics_for(result: ParseResult) -> tuple[Diagnostic, ...]:
    """Return warnings and non-passing validation checks as structured issues."""
    diagnostics: list[Diagnostic] = []
    failed_or_incomplete = {
        check.code for check in result.validation.checks if check.status != "passed"
    }
    for warning in result.warnings:
        if (
            warning.code == "MISSING_ACCOUNT_IDENTITY"
            and "ACCOUNT_IDENTITY" in failed_or_incomplete
        ):
            continue
        locations = (warning.location,) if warning.location else ()
        diagnostics.append(
            Diagnostic(
                code=warning.code,
                severity="warning",
                message=warning.message,
                diagnostic_schema_version="1",
                format=result.source.format,
                source_locations=locations,
                canonical_field=_FIELD_BY_CODE.get(warning.code),
                guidance=_GUIDANCE_BY_CODE.get(warning.code),
            )
        )
    for check in result.validation.checks:
        if check.status == "passed":
            continue
        diagnostics.append(
            Diagnostic(
                code=check.code,
                severity=check.severity,  # type: ignore[arg-type]
                message=check.message,
                diagnostic_schema_version="1",
                format=result.source.format,
                record_indices=check.record_indices,
                source_locations=check.source_locations,
                canonical_field=check.canonical_field or _FIELD_BY_CODE.get(check.code),
                guidance=check.guidance or _GUIDANCE_BY_CODE.get(check.code),
                expected=check.expected,
                actual=check.actual,
            )
        )
    return tuple(diagnostics)


def diagnostic_for_error(error: BankParserError) -> Diagnostic:
    """Return a structured diagnostic for a BankParserError without parsing text."""
    return Diagnostic(
        code=error.code,
        severity="error",
        message=str(error),
        diagnostic_schema_version="1",
        format=error.format,
        record_indices=(error.record_index,) if error.record_index is not None else (),
        source_locations=(error.location,) if error.location else (),
        canonical_field=error.canonical_field or _FIELD_BY_CODE.get(error.code),
        guidance=error.guidance or _GUIDANCE_BY_CODE.get(error.code),
    )
