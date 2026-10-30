from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationCheck,
    ValidationResult,
    Warning,
)
from bankparser.serialization import to_primitive


def test_decimal_and_date_serialize_as_strings() -> None:
    result = ParseResult(
        schema_version="1.0",
        source=SourceMetadata("mt940", "test", "1", "0.1.0"),
        account=Account(currency="GBP"),
        statement=Statement(opening_balance=Decimal("10.00")),
        transactions=(
            Transaction(
                booking_date=date(2026, 10, 1),
                value_date=date(2026, 10, 1),
                amount=Decimal("-2.50"),
                currency="GBP",
            ),
        ),
        validation=ValidationResult(status="passed"),
    )
    primitive = to_primitive(result)
    assert primitive["statement"]["opening_balance"] == "10.00"
    assert primitive["transactions"][0]["booking_date"] == "2026-10-01"
    assert primitive["transactions"][0]["amount"] == "-2.50"


def sensitive_result() -> ParseResult:
    marker = "PRIVATE_MARKER_829174"
    return ParseResult(
        schema_version="1.1",
        source=SourceMetadata("csv", "native", "0.5.0a2", "0.5.0a2", marker),
        account=Account(id=marker, iban=marker, currency="GBP"),
        statement=Statement(id=marker, opening_balance=Decimal("100.00")),
        transactions=(
            Transaction(
                date(2026, 10, 1),
                date(2026, 10, 1),
                Decimal("-2.50"),
                "GBP",
                description=marker,
                reference=marker,
                transaction_id=marker,
                raw={"nested": {"private": marker}},
            ),
        ),
        validation=ValidationResult(
            "warning",
            (
                ValidationCheck(
                    "BALANCE_RECONCILIATION", "skipped", marker, marker, marker
                ),
            ),
        ),
        warnings=(Warning("MISSING_OPENING_BALANCE", marker, marker),),
    )


def test_full_serialization_remains_the_default():
    result = sensitive_result()
    assert to_primitive(result) == to_primitive(result, policy="full")
    assert "raw" in to_primitive(result)["transactions"][0]


def test_canonical_policy_omits_raw_recursively_without_redacting_canonical_fields():
    result = sensitive_result()
    primitive = to_primitive(result, policy="canonical")
    assert "raw" not in primitive["transactions"][0]
    assert primitive["transactions"][0]["description"] == "PRIVATE_MARKER_829174"
    assert primitive["source"]["file_name"] == "PRIVATE_MARKER_829174"


def test_redacted_diagnostic_policy_uses_only_structural_allowlist_and_does_not_mutate():
    result = sensitive_result()
    before = to_primitive(result)
    primitive = to_primitive(result, policy="redacted-diagnostic")
    assert "PRIVATE_MARKER_829174" not in repr(primitive)
    assert primitive["validation"] == {
        "status": "warning",
        "checks": [{"code": "BALANCE_RECONCILIATION", "status": "skipped"}],
    }
    assert primitive["transaction_count"] == 1
    assert to_primitive(result) == before


def test_redacted_policy_drops_unknown_value_types():
    assert (
        to_primitive({"message": "PRIVATE_MARKER_829174"}, policy="redacted-diagnostic")
        is None
    )


def test_redacted_policy_supports_nested_and_direct_diagnostic_models():
    check = ValidationCheck(
        "BALANCE_RECONCILIATION",
        "failed",
        "PRIVATE_MARKER_829174",
        "PRIVATE_MARKER_829174",
        "PRIVATE_MARKER_829174",
    )
    primitive = to_primitive(
        [
            ValidationResult("failed", (check,)),
            Warning("SAFE_CODE", "PRIVATE_MARKER_829174"),
        ],
        policy="redacted-diagnostic",
    )
    assert primitive == [
        {
            "status": "failed",
            "checks": [{"code": "BALANCE_RECONCILIATION", "status": "failed"}],
        },
        {"code": "UNKNOWN_CODE"},
    ]
    assert "PRIVATE_MARKER_829174" not in repr(primitive)


def test_redacted_comparison_omits_difference_paths_and_values():
    from bankparser.comparison import ComparisonDifference, ComparisonReport

    report = ComparisonReport(
        format="csv",
        implementations=("native", "bankstatementparser"),
        matches=False,
        differences=(
            ComparisonDifference(
                "transactions[0].description",
                {"native": "PRIVATE_MARKER_829174"},
            ),
        ),
    )
    primitive = to_primitive(report, policy="redacted-diagnostic")
    assert primitive == {
        "format": "csv",
        "implementations": ["native", "bankstatementparser"],
        "matches": False,
        "difference_count": 1,
    }
    assert "PRIVATE_MARKER_829174" not in repr(primitive)


def test_redacted_assessment_omits_reason_locations_messages_and_fingerprints():
    from bankparser.readiness import (
        DuplicateCandidate,
        ImportAssessment,
        ImportPolicy,
        ImportReason,
    )

    assessment = ImportAssessment(
        assessment_schema_version="1",
        status="review",
        policy=ImportPolicy(),
        destination=None,
        account_origin="missing",
        result_fingerprint="PRIVATE_MARKER_829174",
        recorded_validation_status="warning",
        validation=ValidationResult("warning"),
        reasons=(
            ImportReason(
                "GB75TEST00000000000001",
                "review",
                "PRIVATE_MARKER_829174",
                (0,),
                "PRIVATE_MARKER_829174",
            ),
        ),
        duplicate_candidates=(
            DuplicateCandidate("similar-record", (0, 1), "PRIVATE_MARKER_829174"),
        ),
    )
    primitive = to_primitive(assessment, policy="redacted-diagnostic")
    assert "PRIVATE_MARKER_829174" not in repr(primitive)
    assert "path" not in repr(primitive)
    assert primitive["duplicate_candidate_count"] == 1
    assert primitive["reasons"] == [{"code": "UNKNOWN_CODE", "severity": "review"}]
    assert "GB75TEST00000000000001" not in repr(primitive)


@pytest.mark.parametrize(
    "code", ["GB75TEST00000000000001", "PRIVATE_MARKER_829174", "custom-code", ""]
)
def test_redacted_codes_reject_untrusted_values_in_direct_and_nested_models(code):
    warning = Warning(code, "private message")
    check = ValidationCheck(code, "failed", "private message")
    result = replace(
        sensitive_result(),
        warnings=(warning,),
        validation=ValidationResult("failed", (check,)),
    )
    assert to_primitive(warning, policy="redacted-diagnostic") == {
        "code": "UNKNOWN_CODE"
    }
    assert to_primitive(check, policy="redacted-diagnostic") == {
        "code": "UNKNOWN_CODE",
        "status": "failed",
    }
    redacted = to_primitive(result, policy="redacted-diagnostic")
    assert redacted["warnings"] == [{"code": "UNKNOWN_CODE"}]
    assert redacted["validation"]["checks"][0]["code"] == "UNKNOWN_CODE"
    assert to_primitive(result)["warnings"][0]["code"] == code
