from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from bankparser.parsers.base import ParseContext
from bankparser.parsers.csv.bankstatementparser import BankStatementParserCsvAdapter


class FakeFrame:
    def __init__(self, records):
        self._records = records

    def to_dict(self, orient: str):
        assert orient == "records"
        return self._records


class FakeCsvParser:
    def __init__(self, path: Path) -> None:
        assert path.suffix == ".csv"

    def parse(self):
        return FakeFrame(
            [
                {
                    "date": "2026-10-01",
                    "description": "Salary",
                    "amount": Decimal("1000.00"),
                    "currency": "GBP",
                    "account_id": "GB75TEST00000000000001",
                    "transaction_id": "PAY-001",
                    "balance": "1000.00",
                }
            ]
        )

    def get_summaries(self):
        return [
            {
                "account_id": "GB75TEST00000000000001",
                "currency": "GBP",
                "statement_date": "2026-10-01",
                "transaction_count": 1,
                "total_amount": Decimal("1000.00"),
                "opening_balance": None,
                "closing_balance": Decimal("1000.00"),
            }
        ]


def test_csv_adapter_preserves_source_semantics(monkeypatch) -> None:
    package = ModuleType("bankstatementparser")
    package.__version__ = "0.0.20"
    module = ModuleType("bankstatementparser.additional_parsers")
    module.CsvStatementParser = FakeCsvParser
    monkeypatch.setitem(sys.modules, "bankstatementparser", package)
    monkeypatch.setitem(sys.modules, "bankstatementparser.additional_parsers", module)

    data = (
        b"Booking Date,Description,Amount,Currency,IBAN,Reference,Balance\n"
        b"2026-10-01,Salary,1000.00,GBP,GB75TEST00000000000001,PAY-001,1000.00\n"
    )
    result = BankStatementParserCsvAdapter().parse(data, ParseContext("statement.csv"))

    assert result.account.id == "GB75TEST00000000000001"
    assert result.account.iban == "GB75TEST00000000000001"
    assert result.account.currency == "GBP"
    assert result.statement.opening_balance is None
    assert result.statement.closing_balance is None
    assert result.statement.start_date.isoformat() == "2026-10-01"
    assert result.statement.end_date.isoformat() == "2026-10-01"

    transaction = result.transactions[0]
    assert transaction.booking_date.isoformat() == "2026-10-01"
    assert transaction.value_date is None
    assert transaction.amount == Decimal("1000.00")
    assert transaction.reference == "PAY-001"
    assert transaction.transaction_id is None
    assert transaction.raw["source_balance"] == "1000.00"

    warning_codes = {warning.code for warning in result.warnings}
    assert "CSV_BALANCE_ORDER_UNKNOWN" in warning_codes
    assert "MISSING_OPENING_BALANCE" in warning_codes
    assert "MISSING_CLOSING_BALANCE" in warning_codes
