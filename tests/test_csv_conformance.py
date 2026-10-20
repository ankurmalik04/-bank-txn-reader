from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from bankparser import parse

FIXTURE = Path("corpus/csv/basic_valid.csv")
EXPECTED = Path("corpus/csv/basic_valid.expected.json")


def test_csv_fixture_matches_expected_core(canonical_core) -> None:
    expected = json.loads(EXPECTED.read_text())
    result = parse(FIXTURE)
    actual = canonical_core(result)
    assert actual == expected


def test_csv_split_debit_credit_and_generic_date_semantics() -> None:
    result = parse(Path("corpus/csv/split_debit_credit.csv"))

    assert [transaction.amount for transaction in result.transactions] == [
        Decimal("500.00"),
        Decimal("-18.75"),
    ]
    assert all(transaction.booking_date is None for transaction in result.transactions)
    assert all(transaction.value_date is None for transaction in result.transactions)
    assert [transaction.raw["source_date"] for transaction in result.transactions] == [
        "2026-09-14",
        "2026-09-15",
    ]
    assert result.statement.start_date.isoformat() == "2026-09-14"
    assert result.statement.end_date.isoformat() == "2026-09-15"
    assert "AMBIGUOUS_DATE_SEMANTICS" in {warning.code for warning in result.warnings}
