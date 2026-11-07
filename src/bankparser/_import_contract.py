"""Runtime contract checks for publicly constructible import-assessment inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from bankparser._import_policy import FORMATS, DestinationAccount, ImportPolicy
from bankparser.errors import InputError
from bankparser.models import (
    Account,
    Counterparty,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationCheck,
    ValidationResult,
    Warning,
)

HASH = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_contract(result: ParseResult) -> None:
    # ParseResult is also publicly constructible: annotations alone do not stop
    # a caller from replacing a date with text or an amount with a float.
    def valid(condition: bool) -> None:
        if not condition:
            raise InputError("Invalid canonical field types in import assessment")

    def texts(values: tuple[Any, ...]) -> None:
        valid(all(value is None or isinstance(value, str) for value in values))

    def dates(values: tuple[Any, ...]) -> None:
        valid(
            all(
                value is None
                or isinstance(value, date)
                and not isinstance(value, datetime)
                for value in values
            )
        )

    valid(
        isinstance(result.account, Account) and isinstance(result.statement, Statement)
    )
    texts((result.account.id, result.account.iban, result.account.currency))
    statement = result.statement
    texts(
        (
            statement.id,
            statement.sequence,
            statement.opening_balance_currency,
            statement.closing_balance_currency,
        )
    )
    dates((statement.start_date, statement.end_date))
    valid(
        all(
            value is None or isinstance(value, Decimal)
            for value in (statement.opening_balance, statement.closing_balance)
        )
    )
    valid(isinstance(result.transactions, tuple) and isinstance(result.warnings, tuple))
    for tx in result.transactions:
        valid(isinstance(tx, Transaction) and isinstance(tx.counterparty, Counterparty))
        valid(isinstance(tx.amount, Decimal) and isinstance(tx.raw, Mapping))
        dates((tx.booking_date, tx.value_date))
        texts(
            (
                tx.currency,
                tx.description,
                tx.reference,
                tx.transaction_id,
                tx.counterparty.name,
                tx.counterparty.account_id,
                tx.counterparty.iban,
            )
        )
    valid(
        all(
            isinstance(warning, Warning) and isinstance(warning.code, str)
            for warning in result.warnings
        )
    )
    valid(all(isinstance(check.code, str) for check in result.validation.checks))


def validate_assessment_inputs(
    result: ParseResult,
    policy: ImportPolicy | None,
    destination: DestinationAccount | None,
    reviewed_duplicates: tuple[str, ...],
) -> None:
    if not isinstance(result, ParseResult) or (
        policy is not None and not isinstance(policy, ImportPolicy)
    ):
        raise InputError(
            "assess_import requires a ParseResult and optional ImportPolicy"
        )
    if not isinstance(result.source, SourceMetadata) or not isinstance(
        result.validation, ValidationResult
    ):
        raise InputError("Invalid source or recorded validation object")
    if result.validation.status not in ("passed", "warning", "failed") or any(
        not isinstance(c, ValidationCheck)
        or c.status not in ("passed", "skipped", "failed")
        for c in result.validation.checks
    ):
        raise InputError("Invalid recorded validation status/checks")
    if (
        result.schema_version != "1.1"
        or not isinstance(result.source.format, str)
        or result.source.format not in FORMATS
    ):
        raise InputError(
            "Import assessment requires canonical schema 1.1 and a supported format"
        )
    if destination is not None and not isinstance(destination, DestinationAccount):
        raise InputError("destination must be DestinationAccount")
    if not isinstance(reviewed_duplicates, tuple) or any(
        not isinstance(v, str) or HASH.fullmatch(v) is None for v in reviewed_duplicates
    ):
        raise InputError(
            "reviewed_duplicates must be a tuple of candidate fingerprints"
        )
    if len(set(reviewed_duplicates)) != len(reviewed_duplicates):
        raise InputError("Duplicate review tokens must be unique")
    _canonical_contract(result)
