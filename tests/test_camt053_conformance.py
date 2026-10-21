from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bankparser import parse

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install the camt extra to run CAMT.053 conformance tests",
)

FIXTURE = Path("corpus/camt053/basic_valid.camt053.xml")
EXPECTED = Path("corpus/camt053/basic_valid.expected.json")


def test_camt053_fixture_matches_expected_core(canonical_core) -> None:
    expected = json.loads(EXPECTED.read_text())
    result = parse(FIXTURE)
    actual = canonical_core(result)
    assert actual == expected


def with_period(period: str) -> bytes:
    return FIXTURE.read_bytes().replace(
        b"<Acct>", f"<FrToDt>{period}</FrToDt><Acct>".encode(), 1
    )


def test_reporting_period_takes_precedence_over_balance_dates():
    result = parse(
        with_period(
            "<FrDtTm>2026-09-15T00:10:00+02:00</FrDtTm>"
            "<ToDtTm>2026-09-17T23:10:00-02:00</ToDtTm>"
        )
    )
    # Preserve source-local dates rather than shifting to UTC or balance dates.
    assert str(result.statement.start_date) == "2026-09-15"
    assert str(result.statement.end_date) == "2026-09-17"
    assert result.validation.status == "passed"


def test_absent_period_bound_falls_back_independently():
    result = parse(with_period("<FrDtTm>2026-09-15T00:00:00Z</FrDtTm>"))
    assert str(result.statement.start_date) == "2026-09-15"
    assert str(result.statement.end_date) == "2026-09-16"


@pytest.mark.parametrize("value", ["", "bad", "2026-02-30T00:00:00Z", "2026-09-15"])
def test_invalid_explicit_period_does_not_silently_fall_back(value):
    from bankparser import ParseError

    with pytest.raises(ParseError) as caught:
        parse(with_period(f"<FrDtTm>{value}</FrDtTm>"))
    assert caught.value.code == "INVALID_STATEMENT_DATE"
    assert caught.value.location == "Stmt/FrToDt/FrDtTm"


def test_reversed_explicit_period_fails_shared_validation():
    result = parse(
        with_period(
            "<FrDtTm>2026-09-17T00:00:00Z</FrDtTm><ToDtTm>2026-09-15T00:00:00Z</ToDtTm>"
        )
    )
    assert result.validation.status == "failed"
    assert (
        next(
            c for c in result.validation.checks if c.code == "STATEMENT_DATE_ORDER"
        ).status
        == "failed"
    )


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("SYNTH-TX-42", "SYNTH-TX-42"),
        (" NOTPROVIDED ", None),
        ("", None),
    ],
)
def test_source_transaction_id_is_separate_from_payment_reference(identifier, expected):
    data = FIXTURE.read_bytes().replace(
        b"<Refs>", f"<Refs><TxId>{identifier}</TxId>".encode(), 1
    )
    result = parse(data)
    first, second = result.transactions
    assert first.transaction_id == expected
    assert first.reference == "SYNTH-E2E-1"
    assert second.transaction_id is None
    assert second.reference == "SYNTH-E2E-2"
    if identifier.strip():
        assert first.raw["payment_references"]["TxId"] == identifier.strip()


def test_duplicate_period_bounds_are_rejected():
    from bankparser import ParseError

    with pytest.raises(ParseError) as caught:
        parse(
            with_period(
                "<FrDtTm>2026-09-15T00:00:00Z</FrDtTm>"
                "<FrDtTm>2026-09-16T00:00:00Z</FrDtTm>"
            )
        )
    assert caught.value.code == "INVALID_STATEMENT_DATE"


def test_invalid_end_bound_is_rejected():
    from bankparser import ParseError

    with pytest.raises(ParseError) as caught:
        parse(with_period("<ToDtTm>invalid</ToDtTm>"))
    assert caught.value.code == "INVALID_STATEMENT_DATE"
    assert caught.value.location == "Stmt/FrToDt/ToDtTm"
