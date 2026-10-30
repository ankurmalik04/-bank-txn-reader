"""JSON-safe serialization for canonical models."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Literal

OutputPolicy = Literal["full", "canonical", "redacted-diagnostic"]
_FORMATS = frozenset({"csv", "mt940", "camt053", "ofx"})
_IMPLEMENTATIONS = frozenset({"native", "wolph", "bankstatementparser", "ofxparse"})
_STATUSES = frozenset(
    {"passed", "warning", "failed", "skipped", "ready", "review", "not-ready"}
)
# Static, reviewed built-in diagnostics only. New codes require explicit review;
# custom diagnostics must never expand this privacy allowlist at runtime.
_TRUSTED_CODES = frozenset(
    {
        "ACCOUNT_IDENTITY",
        "AMBIGUOUS_AMOUNT",
        "AMBIGUOUS_BALANCE",
        "AMBIGUOUS_COLUMNS",
        "AMBIGUOUS_CSV_HEADER",
        "AMBIGUOUS_DATE_SEMANTICS",
        "AMBIGUOUS_MOVEMENT",
        "AMBIGUOUS_TRANSACTION_ALIGNMENT",
        "BALANCE_RECONCILIATION",
        "BANKPARSER_ERROR",
        "CAMT_BATCH_TOTAL_MISMATCH",
        "CAMT_DIRECTION_CONFLICT",
        "CLI_USAGE_ERROR",
        "COMPARISON_ERROR",
        "CONFIGURED_CURRENCY",
        "CSV_BALANCE_ORDER_UNKNOWN",
        "CSV_CURRENCY_CONSTRAINT",
        "CURRENCY_CONSISTENCY",
        "DESTINATION_ACCOUNT_CONFLICT",
        "DESTINATION_CURRENCY_CONFLICT",
        "DUPLICATE_CANDIDATE",
        "DUPLICATE_TRANSACTION_ID",
        "EMPTY_ACTIVITY",
        "EMPTY_STATEMENT",
        "FAILED_VALIDATION",
        "FINITE_AMOUNTS",
        "INCOMPLETE_OUTPUT",
        "INCOMPLETE_VALIDATION",
        "INPUT_ERROR",
        "INVALID_AMOUNT",
        "INVALID_CAMT_AMOUNT_STRUCTURE",
        "INVALID_CAMT_DIRECTION",
        "INVALID_CSV",
        "INVALID_CSV_HEADER",
        "INVALID_CSV_ROW",
        "INVALID_CURRENCY",
        "INVALID_DATE",
        "INVALID_ENCODING",
        "INVALID_OFX_STRUCTURE",
        "INVALID_STATEMENT_DATE",
        "MISSING_ACCOUNT_IDENTITY",
        "MISSING_AMOUNT",
        "MISSING_BOOKING_DATE",
        "MISSING_CAMT_CURRENCY",
        "MISSING_CLOSING_BALANCE",
        "MISSING_CLOSING_BALANCE_CURRENCY",
        "MISSING_CSV_COLUMN",
        "MISSING_CURRENCY",
        "MISSING_DEPENDENCY",
        "MISSING_DESCRIPTION",
        "MISSING_OPENING_BALANCE",
        "MISSING_OPENING_BALANCE_CURRENCY",
        "MISSING_REFERENCE",
        "MISSING_STATEMENT_PERIOD",
        "MISSING_TRANSACTION_CURRENCY",
        "MISSING_VALUE_DATE",
        "MULTIPLE_STATEMENTS",
        "OFX_BACKEND_ERROR",
        "OFX_BACKEND_MISMATCH",
        "OFX_BACKEND_WARNING",
        "OFX_RESPONSE_ERROR",
        "OFX_RESPONSE_WARNING",
        "PARSER_WARNING",
        "PARSE_ERROR",
        "SIGNED_CAMT_AMOUNT",
        "SIGNED_DEBIT_CREDIT",
        "STATEMENT_DATE_ORDER",
        "TRANSACTION_ALIGNMENT_MISMATCH",
        "TRANSACTION_BOOKING_DATES",
        "TRANSACTION_COUNT_MISMATCH",
        "TRANSACTION_CURRENCIES",
        "TRANSACTION_VALUE_DATES",
        "UNCONFIRMED_ACCOUNT_MAPPING",
        "UNEXPLAINED_VALIDATION_WARNING",
        "UNKNOWN_CODE",
        "UNKNOWN_IMPLEMENTATION",
        "UNPARSED_TRANSACTION_DATE",
        "UNSUPPORTED_CORRECTION",
        "UNSUPPORTED_ENTRY_STATUS",
        "UNSUPPORTED_FORMAT",
        "UNSUPPORTED_OFX_PROFILE",
        "UNSUPPORTED_OFX_SCOPE",
        "UNSUPPORTED_PENDING_ACTIVITY",
        "UNSUPPORTED_TRANSACTION",
        "UNSUPPORTED_TRANSACTION_CURRENCY",
        "VALUE_DATE_OUTSIDE_PERIOD",
    }
)


def to_primitive(value: Any, *, policy: OutputPolicy = "full") -> Any:
    """Convert values to JSON primitives under an explicit output policy.

    ``full`` preserves the historical serialization contract. ``canonical``
    omits every dataclass field named ``raw`` but retains other canonical fields,
    which may still contain sensitive financial or identity data.
    ``redacted-diagnostic`` emits a small type-specific allowlist of structural
    status and code fields; it is not a promise of anonymity.
    """
    if policy not in {"full", "canonical", "redacted-diagnostic"}:
        raise ValueError(f"Unknown serialization policy: {policy!r}")
    if policy == "redacted-diagnostic":
        return _redacted_diagnostic(value)
    return _serialize(value, omit_raw=policy == "canonical")


def _serialize(value: Any, *, omit_raw: bool) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: _serialize(getattr(value, field.name), omit_raw=omit_raw)
            for field in dataclasses.fields(value)
            if not field.metadata.get("diagnostic_only", False)
            and not (omit_raw and field.name == "raw")
        }
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize(item, omit_raw=omit_raw) for item in value]
    if isinstance(value, list):
        return [_serialize(item, omit_raw=omit_raw) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _serialize(item, omit_raw=omit_raw) for key, item in value.items()
        }
    return value


def _redacted_diagnostic(value: Any) -> Any:
    """Serialize known public reports through a deliberately narrow allowlist."""
    if isinstance(value, (tuple, list)):
        return [_redacted_diagnostic(item) for item in value]
    name = type(value).__name__
    if name == "ParseResult":
        source = value.source
        return {
            "schema_version": _safe_version(value.schema_version),
            "format": source.format if source.format in _FORMATS else None,
            "validation": _redacted_validation(value.validation),
            "warnings": _redacted_warnings(value.warnings),
            "transaction_count": len(value.transactions),
        }
    if name == "ComparisonReport":
        return {
            "format": value.format if value.format in _FORMATS else None,
            "implementations": [
                item for item in value.implementations if item in _IMPLEMENTATIONS
            ],
            "matches": bool(value.matches),
            "difference_count": len(value.differences),
        }
    if name == "ImportAssessment":
        return {
            "assessment_schema_version": _safe_version(value.assessment_schema_version),
            "status": value.status
            if value.status in {"ready", "review", "not-ready"}
            else None,
            "recorded_validation_status": (
                value.recorded_validation_status
                if value.recorded_validation_status in _STATUSES
                else None
            ),
            "validation": _redacted_validation(value.validation),
            "reasons": [
                {
                    "code": _safe_code(reason.code),
                    "severity": reason.severity
                    if reason.severity in {"review", "block"}
                    else None,
                }
                for reason in value.reasons
            ],
            "duplicate_candidate_count": len(value.duplicate_candidates),
        }
    if name == "ValidationResult":
        return _redacted_validation(value)
    if name == "Diagnostic":
        return {
            "diagnostic_schema_version": "1",
            "code": _safe_code(value.code),
            "severity": value.severity
            if value.severity in {"info", "warning", "error"}
            else None,
            "format": value.format if value.format in _FORMATS else None,
            "canonical_field": _safe_field(value.canonical_field),
        }
    if name == "ValidationCheck":
        return {
            "code": _safe_code(value.code),
            "status": value.status if value.status in _STATUSES else None,
        }
    if name == "Warning":
        return {"code": _safe_code(value.code)}
    if name == "SourceMetadata":
        return {"format": value.format if value.format in _FORMATS else None}
    # Unknown types and mappings have no safe fields by default.
    return None


def _redacted_validation(value: Any) -> dict[str, Any]:
    status = value.status if value.status in _STATUSES else None
    return {
        "status": status,
        "checks": [
            {
                "code": _safe_code(check.code),
                "status": check.status if check.status in _STATUSES else None,
            }
            for check in value.checks
        ],
    }


def _redacted_warnings(values: Any) -> list[dict[str, str | None]]:
    return [{"code": _safe_code(item.code)} for item in values]


def _safe_code(value: Any) -> str:
    return (
        value if isinstance(value, str) and value in _TRUSTED_CODES else "UNKNOWN_CODE"
    )


def _safe_version(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 24:
        return None
    return value if re.fullmatch(r"[0-9]+(?:\.[0-9A-Za-z.+-]+)*", value) else None


def _safe_field(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 80:
        return None
    return value if re.fullmatch(r"[a-z][a-z0-9_.]*", value) else None
