"""Destination import assessment orchestration and stable public exports."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from bankparser._import_contract import validate_assessment_inputs
from bankparser._import_duplicates import DuplicateCandidate, _duplicates, _fingerprint
from bankparser._import_models import ImportAssessment, ImportReason, ReadinessStatus
from bankparser._import_policy import (
    Action,
    DestinationAccount,
    ImportPolicy,
    load_import_policy,
)
from bankparser.errors import InputError
from bankparser.models import ParseResult
from bankparser.serialization import to_primitive
from bankparser.validation import validate

__all__ = [
    "Action",
    "DestinationAccount",
    "DuplicateCandidate",
    "ImportAssessment",
    "ImportPolicy",
    "ImportReason",
    "ReadinessStatus",
    "assess_import",
    "load_import_policy",
]

CORE_CHECKS = frozenset(
    {
        "BALANCE_RECONCILIATION",
        "CURRENCY_CONSISTENCY",
        "CURRENCY_FORMAT",
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


def assess_import(
    result: ParseResult,
    policy: ImportPolicy | None = None,
    *,
    destination: DestinationAccount | None = None,
    reviewed_duplicates: tuple[str, ...] = (),
) -> ImportAssessment:
    """Assess existing canonical data; never mutate, fill, delete or import it.

    Failed recorded and freshly recomputed checks always block. Duplicate review
    fingerprints bind to this whole canonical result, resolved policy and
    destination context, not original file bytes.
    """
    validate_assessment_inputs(result, policy, destination, reviewed_duplicates)
    policy = policy or ImportPolicy()
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
        candidates = _duplicates(result, fingerprint, policy, destination)
    except (TypeError, AttributeError, ValueError) as exc:
        raise InputError("Invalid canonical field types in import assessment") from exc
    if set(reviewed_duplicates) - {c.fingerprint for c in candidates}:
        raise InputError(
            "Duplicate review token does not apply to this canonical result, "
            "policy or destination context"
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
