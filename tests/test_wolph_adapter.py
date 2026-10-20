from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bankparser.parsers.base import ParseContext
from bankparser.parsers.mt940.wolph import WolphMt940Adapter


class Amount:
    def __init__(self, value: str, currency: str = "GBP") -> None:
        self.amount = Decimal(value)
        self.currency = currency


class Balance:
    def __init__(self, value: str, day: date) -> None:
        self.amount = Amount(value)
        self.date = day


class Transaction:
    def __init__(
        self,
        amount: str,
        value_day: date,
        description: str,
        *,
        entry_day: date | None = None,
    ) -> None:
        self.data = {
            "date": value_day,
            "entry_date": entry_day,
            "amount": Amount(amount),
            "transaction_details": description,
            "customer_reference": "CUSTOMER-REF",
            "bank_reference": "BANK-REF",
        }


class NativeStatement(list):
    def __init__(self) -> None:
        super().__init__(
            [
                Transaction(
                    "-25.50",
                    date(2026, 10, 2),
                    "Coffee shop",
                    entry_day=None,
                ),
                Transaction(
                    "200.00",
                    date(2026, 10, 3),
                    "Salary",
                    entry_day=date(2026, 10, 4),
                ),
            ]
        )
        self.data = {
            "account_identification": "GB75TEST00000000000001",
            "transaction_reference": "EXAMPLE-001",
            "statement_number": "1",
            "sequence_number": "1",
            "final_opening_balance": Balance("1000.00", date(2026, 10, 1)),
            "final_closing_balance": Balance("1174.50", date(2026, 10, 5)),
        }


class FakeOptions:
    def __init__(self, **kwargs: bool) -> None:
        self.values = kwargs


def test_wolph_adapter_maps_native_objects_without_inventing_dates(monkeypatch) -> None:
    fake_mt940 = SimpleNamespace(
        __version__="5.1.1",
        Options=FakeOptions,
        parse_statements=lambda data, options: [NativeStatement()],
    )
    monkeypatch.setitem(sys.modules, "mt940", fake_mt940)

    adapter = WolphMt940Adapter()
    result = adapter.parse(
        Path("corpus/mt940/basic_valid.mt940").read_bytes(), ParseContext("test.mt940")
    )

    assert adapter.implementation_version == "5.1.1"
    assert result.account.currency == "GBP"
    assert result.account.iban is None
    assert result.statement.opening_balance == Decimal("1000.00")
    assert result.statement.start_date == date(2026, 10, 1)
    assert result.statement.end_date == date(2026, 10, 5)
    assert result.transactions[0].amount == Decimal("-25.50")
    assert result.transactions[0].description == "Coffee shop"
    assert result.transactions[0].reference == "CUSTOMER-REF"
    assert result.transactions[0].value_date == date(2026, 10, 2)
    assert result.transactions[0].booking_date is None
    assert result.transactions[1].booking_date == date(2026, 10, 4)
