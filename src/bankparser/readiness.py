"""Destination import suitability, separate from source parsing and validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from decimal import Decimal
from os import PathLike
from pathlib import Path
from typing import Any, Literal

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
from bankparser.serialization import to_primitive
from bankparser.validation import validate

Action = Literal["ignore", "review", "block"]
ReadinessStatus = Literal["ready", "review", "not-ready"]
ACTIONS = frozenset({"ignore", "review", "block"})
FORMATS = frozenset({"csv", "mt940", "camt053", "ofx"})
HASH = re.compile(r"[0-9a-f]{64}\Z")
CORE_CHECKS = frozenset(
    {
        "BALANCE_RECONCILIATION",
        "CURRENCY_CONSISTENCY",
        "FINITE_AMOUNTS",
        "STATEMENT_DATE_ORDER",
        "TRANSACTION_CURRENCIES",
        "TRANSACTION_BOOKING_DATES",
        "TRANSACTION_VALUE_DATES",
        "ACCOUNT_IDENTITY",
    }
)
FIELD_WARNINGS = frozenset(
    {
        "MISSING_CURRENCY",
        "MISSING_OPENING_BALANCE",
        "MISSING_CLOSING_BALANCE",
        "MISSING_ACCOUNT_IDENTITY",
        "AMBIGUOUS_DATE_SEMANTICS",
        "UNPARSED_TRANSACTION_DATE",
        "CSV_BALANCE_ORDER_UNKNOWN",
        "CONFIGURED_CURRENCY",
    }
)


def _text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


@dataclass(frozen=True, slots=True)
class ImportPolicy:
    """Missing-field and review actions; none can override a failed invariant."""

    id: str = "default"
    version: str = "1"
    booking_date: Action = "block"
    value_date: Action = "ignore"
    transaction_currency: Action = "block"
    account_identity: Action = "review"
    description: Action = "ignore"
    reference: Action = "ignore"
    opening_balance: Action = "ignore"
    closing_balance: Action = "ignore"
    statement_period: Action = "ignore"
    duplicate_candidates: Action = "review"
    configured_currency: Action = "review"
    value_date_outside_period: Action = "review"
    other_incomplete_checks: Action = "review"
    other_warnings: Action = "review"
    empty_activity: Action = "review"
    allow_destination_account: bool = True
    value_date_exempt_formats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("id", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InputError("Import policy id/version must be nonblank text")
        for field in fields(self):
            if field.name not in {
                "id",
                "version",
                "allow_destination_account",
                "value_date_exempt_formats",
            }:
                value = getattr(self, field.name)
                if not isinstance(value, str) or value not in ACTIONS:
                    raise InputError(
                        f"Import policy {field.name} must be ignore, review or block"
                    )
        if type(self.allow_destination_account) is not bool:
            raise InputError("allow_destination_account must be boolean")
        if (
            not isinstance(self.value_date_exempt_formats, tuple)
            or any(
                not isinstance(v, str) or v not in FORMATS
                for v in self.value_date_exempt_formats
            )
            or len(set(self.value_date_exempt_formats))
            != len(self.value_date_exempt_formats)
        ):
            raise InputError(
                "value_date_exempt_formats must be a tuple of unique supported formats"
            )


def load_import_policy(path: str | PathLike[str]) -> ImportPolicy:
    """Read a data-only v1 policy, bounded to 64 KiB, without executing code."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise InputError("Duplicate JSON key in import policy")
            value[key] = item
        return value

    def constant(value: str) -> Any:
        raise InputError("Nonfinite JSON number in import policy")

    try:
        with Path(path).open("rb") as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise InputError("Import policy exceeds 64 KiB")
        document = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant
        )
        if not isinstance(document, dict) or set(document) != {
            "policy_schema_version",
            "policy",
        }:
            raise InputError("Import policy has missing or unknown fields")
        if document["policy_schema_version"] != "1" or not isinstance(
            document["policy"], dict
        ):
            raise InputError("Unsupported import policy schema or policy object")
        options = document["policy"]
        if "value_date_exempt_formats" in options:
            if not isinstance(options["value_date_exempt_formats"], list):
                raise InputError("JSON value_date_exempt_formats must be an array")
            options["value_date_exempt_formats"] = tuple(
                options["value_date_exempt_formats"]
            )
        return ImportPolicy(**options)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise InputError("Cannot load valid UTF-8 import policy/options") from exc


@dataclass(frozen=True, slots=True)
class DestinationAccount:
    """Caller-declared ledger destination, never inserted into source account data."""

    id: str
    currency: str | None = None
    source_account_id: str | None = None
    source_iban: str | None = None
    mapping_confirmed: bool = False

    def __post_init__(self) -> None:
        for name in ("id", "source_account_id", "source_iban"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise InputError("Destination identifiers must be nonblank text")
        if not isinstance(self.id, str):
            raise InputError("Destination account id is required")
        if self.currency is not None:
            if (
                not isinstance(self.currency, str)
                or re.fullmatch(r"[A-Za-z]{3}", self.currency) is None
            ):
                raise InputError("Destination currency must be three ASCII letters")
            object.__setattr__(self, "currency", self.currency.upper())
        if type(self.mapping_confirmed) is not bool:
            raise InputError("Destination mapping_confirmed must be boolean")


@dataclass(frozen=True, slots=True)
class ImportReason:
    """Structured blocker/review reason; indices are zero-based source positions."""

    code: str
    severity: Literal["review", "block"]
    path: str
    transaction_indices: tuple[int, ...]
    message: str
    source_code: str | None = None


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """An intra-result review candidate, not proof of a duplicate payment."""

    kind: Literal["transaction-id", "similar-record"]
    transaction_indices: tuple[int, ...]
    fingerprint: str
    reviewed: bool = False


@dataclass(frozen=True, slots=True)
class ImportAssessment:
    """Version-1 destination assessment; canonical parse schema remains separate."""

    assessment_schema_version: str
    status: ReadinessStatus
    policy: ImportPolicy
    destination: DestinationAccount | None
    account_origin: Literal["source", "destination-context", "missing"]
    result_fingerprint: str
    recorded_validation_status: str
    validation: ValidationResult
    reasons: tuple[ImportReason, ...]
    duplicate_candidates: tuple[DuplicateCandidate, ...]


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            to_primitive(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _duplicates(
    result: ParseResult, fingerprint: str
) -> tuple[DuplicateCandidate, ...]:
    ids: dict[str, list[int]] = {}
    signatures: dict[tuple[Any, ...], list[int]] = {}
    for index, tx in enumerate(result.transactions):
        identity = _text(tx.transaction_id)
        if identity:
            ids.setdefault(identity, []).append(index)
        if tx.amount.is_finite():
            signature = (
                tx.booking_date,
                tx.value_date,
                tx.amount,
                _text(tx.currency),
                tx.description,
                tx.reference,
                tx.counterparty.name,
                tx.counterparty.account_id,
                tx.counterparty.iban,
            )
            signatures.setdefault(signature, []).append(index)
    groups: dict[tuple[int, ...], Literal["transaction-id", "similar-record"]] = {}
    for indices in signatures.values():
        if len(indices) > 1:
            groups[tuple(indices)] = "similar-record"
    for indices in ids.values():
        if len(indices) > 1:
            groups[tuple(indices)] = "transaction-id"
    return tuple(
        DuplicateCandidate(
            kind,
            indices,
            _fingerprint(
                {
                    "version": "1",
                    "result": fingerprint,
                    "kind": kind,
                    "indices": indices,
                }
            ),
        )
        for indices, kind in sorted(groups.items())
    )


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


def assess_import(
    result: ParseResult,
    policy: ImportPolicy | None = None,
    *,
    destination: DestinationAccount | None = None,
    reviewed_duplicates: tuple[str, ...] = (),
) -> ImportAssessment:
    """Assess existing canonical data; never mutate, fill, delete or import it.

    Failed recorded and freshly recomputed checks always block. Duplicate review
    fingerprints bind to this whole canonical result, not original file bytes.
    """
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
    policy = policy or ImportPolicy()
    _canonical_contract(result)
    try:
        validation = validate(result.account, result.statement, result.transactions)
        canonical = {
            "schema_version": result.schema_version,
            "format": result.source.format,
            "account": result.account,
            "statement": result.statement,
            "transactions": [
                {k: v for k, v in to_primitive(tx).items() if k != "raw"}
                for tx in result.transactions
            ],
        }
        fingerprint = _fingerprint(canonical)
        candidates = _duplicates(result, fingerprint)
    except (TypeError, AttributeError, ValueError) as exc:
        raise InputError("Invalid canonical field types in import assessment") from exc
    if set(reviewed_duplicates) - {c.fingerprint for c in candidates}:
        raise InputError(
            "Duplicate review token does not apply to this canonical result"
        )
    candidates = tuple(
        replace(c, reviewed=c.fingerprint in reviewed_duplicates) for c in candidates
    )
    reasons: list[ImportReason] = []

    def add(
        action: Action,
        code: str,
        path: str,
        message: str,
        indices: tuple[int, ...] = (),
        source_code: str | None = None,
    ) -> None:
        if action != "ignore":
            reasons.append(
                ImportReason(code, action, path, indices, message, source_code)
            )

    failed = sorted(
        {
            c.code
            for report in (result.validation, validation)
            for c in report.checks
            if c.status == "failed"
        }
    )
    for code in failed:
        add(
            "block",
            "FAILED_VALIDATION",
            "validation",
            "Recorded or recomputed validation failed; policy cannot override",
            source_code=code,
        )
    if result.validation.status == "failed" and not failed:
        add(
            "block",
            "FAILED_VALIDATION",
            "validation",
            "Recorded validation aggregate failed without individual failed checks",
        )

    identity_present = bool(_text(result.account.id) or _text(result.account.iban))
    contextual_identity = bool(
        destination
        and destination.mapping_confirmed
        and policy.allow_destination_account
    )
    account_origin: Literal["source", "destination-context", "missing"] = (
        "source"
        if identity_present
        else "destination-context"
        if contextual_identity
        else "missing"
    )
    if not identity_present and not contextual_identity:
        add(
            policy.account_identity,
            "MISSING_ACCOUNT_IDENTITY",
            "account",
            "No source identity or permitted confirmed destination mapping",
        )
    if destination:
        if not destination.mapping_confirmed:
            add(
                "review",
                "UNCONFIRMED_ACCOUNT_MAPPING",
                "destination",
                "Caller must confirm the destination mapping",
            )
        for field, expected in (
            ("id", destination.source_account_id),
            ("iban", destination.source_iban),
        ):
            actual = _text(getattr(result.account, field))
            if actual and expected is not None and actual != _text(expected):
                add(
                    "block",
                    "DESTINATION_ACCOUNT_CONFLICT",
                    "account." + field,
                    "Known source identity conflicts with destination's expected source identity",
                )
        if destination.currency:
            known = [
                result.account.currency,
                result.statement.opening_balance_currency,
                result.statement.closing_balance_currency,
                *(t.currency for t in result.transactions),
            ]
            if any(v and v.strip().upper() != destination.currency for v in known):
                add(
                    "block",
                    "DESTINATION_CURRENCY_CONFLICT",
                    "destination.currency",
                    "Known source currency conflicts with destination currency",
                )

    for field, action in (
        ("booking_date", policy.booking_date),
        ("value_date", policy.value_date),
        ("currency", policy.transaction_currency),
        ("description", policy.description),
        ("reference", policy.reference),
    ):
        if (
            field == "value_date"
            and result.source.format in policy.value_date_exempt_formats
        ):
            continue
        missing = tuple(
            i
            for i, tx in enumerate(result.transactions)
            if getattr(tx, field) is None
            or isinstance(getattr(tx, field), str)
            and not getattr(tx, field).strip()
        )
        if missing:
            add(
                action,
                "MISSING_TRANSACTION_CURRENCY"
                if field == "currency"
                else "MISSING_" + field.upper(),
                "transactions[]." + field,
                "Required destination field is missing",
                missing,
            )
    for field, action in (
        ("opening_balance", policy.opening_balance),
        ("closing_balance", policy.closing_balance),
    ):
        if getattr(result.statement, field) is None:
            add(
                action,
                "MISSING_" + field.upper(),
                "statement." + field,
                "Destination balance prerequisite is missing",
            )
        elif not _text(getattr(result.statement, field + "_currency")):
            add(
                action,
                "MISSING_" + field.upper() + "_CURRENCY",
                "statement." + field + "_currency",
                "Required balance has no source currency",
            )
    if result.statement.start_date is None or result.statement.end_date is None:
        add(
            policy.statement_period,
            "MISSING_STATEMENT_PERIOD",
            "statement",
            "Complete source statement period is unavailable",
        )
    outside = tuple(
        i
        for i, tx in enumerate(result.transactions)
        if tx.value_date is not None
        and (
            result.statement.start_date is not None
            and tx.value_date < result.statement.start_date
            or result.statement.end_date is not None
            and tx.value_date > result.statement.end_date
        )
    )
    if outside:
        add(
            policy.value_date_outside_period,
            "VALUE_DATE_OUTSIDE_PERIOD",
            "transactions[].value_date",
            "Settlement date outside reported bounds requires destination-specific review",
            outside,
        )
    if not result.transactions:
        add(
            policy.empty_activity,
            "EMPTY_ACTIVITY",
            "transactions",
            "No movements are available to import",
        )
    configured = tuple(
        i
        for i, tx in enumerate(result.transactions)
        if isinstance(tx.raw.get("csv_configuration"), dict)
        and tx.raw["csv_configuration"].get("currency_origin") == "configured-default"
    )
    if configured or any(w.code == "CONFIGURED_CURRENCY" for w in result.warnings):
        add(
            policy.configured_currency,
            "CONFIGURED_CURRENCY",
            "transactions[].currency",
            "Currency was supplied by configuration, not the source",
            configured,
        )
    for code in sorted(
        {
            c.code
            for report in (result.validation, validation)
            for c in report.checks
            if c.status == "skipped" and c.code not in CORE_CHECKS
        }
    ):
        add(
            policy.other_incomplete_checks,
            "INCOMPLETE_VALIDATION",
            "validation",
            "Additional validation prerequisite was skipped",
            source_code=code,
        )
    if result.validation.status == "warning" and not any(
        c.status in {"skipped", "failed"} for c in result.validation.checks
    ):
        add(
            policy.other_incomplete_checks,
            "UNEXPLAINED_VALIDATION_WARNING",
            "validation",
            "Recorded warning aggregate has no explanatory skipped checks",
        )
    for code in sorted(
        {w.code for w in result.warnings if w.code not in FIELD_WARNINGS}
    ):
        add(
            policy.other_warnings,
            "PARSER_WARNING",
            "warnings",
            "Additional parser warning requires review",
            source_code=code,
        )
    for candidate in candidates:
        if not candidate.reviewed:
            add(
                policy.duplicate_candidates,
                "DUPLICATE_CANDIDATE",
                "transactions",
                "Candidate repeated identity or similar record; never automatically removed",
                candidate.transaction_indices,
                candidate.kind,
            )
    status: ReadinessStatus = (
        "not-ready"
        if any(r.severity == "block" for r in reasons)
        else "review"
        if reasons
        else "ready"
    )
    return ImportAssessment(
        "1",
        status,
        policy,
        destination,
        account_origin,
        fingerprint,
        result.validation.status,
        validation,
        tuple(reasons),
        candidates,
    )
