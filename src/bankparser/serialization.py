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
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


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
            if not (omit_raw and field.name == "raw")
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


def _safe_code(value: Any) -> str | None:
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def _safe_version(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 24:
        return None
    return value if re.fullmatch(r"[0-9]+(?:\.[0-9A-Za-z.+-]+)*", value) else None
