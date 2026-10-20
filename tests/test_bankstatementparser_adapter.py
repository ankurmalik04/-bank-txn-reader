from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from bankparser.parsers.base import ParseContext
from bankparser.parsers.mt940.bankstatementparser import (
    BankStatementParserMt940Adapter,
)


class FakeFrame:
    def to_dict(self, orient: str):
        assert orient == "records"
        return [
            {
                "date": "2026-09-15",
                "amount": Decimal("-18.75"),
                "currency": "GBP",
                "description": "Test materials",
                "transaction_id": "NTRFMATERIAL//SYNTH-BANK-1",
            },
            {
                "date": "2026-09-16",
                "amount": Decimal("80.00"),
                "currency": "GBP",
                "description": "Test contribution",
                "transaction_id": "NTRFDONATION//SYNTH-BANK-2",
            },
        ]


class FakeMt940Parser:
    def __init__(self, file_name: str | Path) -> None:
        self.path = Path(file_name)
        assert (
            self.path.read_bytes()
            == Path("corpus/mt940/basic_valid.mt940").read_bytes()
        )

    def parse(self) -> FakeFrame:
        return FakeFrame()

    def get_summaries(self):
        return [
            {
                "account_id": "GB75TEST00000000000001",
                "currency": "GBP",
                "statement_date": "2026-09-16",
                "opening_balance": Decimal("500.00"),
                "closing_balance": Decimal("561.25"),
                "statement_id": "1/1",
            }
        ]


def test_bankstatementparser_adapter_maps_normalized_output(monkeypatch) -> None:
    package = ModuleType("bankstatementparser")
    package.__version__ = "0.0.20"
    additional = ModuleType("bankstatementparser.additional_parsers")
    additional.Mt940Parser = FakeMt940Parser

    monkeypatch.setitem(sys.modules, "bankstatementparser", package)
    monkeypatch.setitem(
        sys.modules, "bankstatementparser.additional_parsers", additional
    )

    adapter = BankStatementParserMt940Adapter()
    result = adapter.parse(
        Path("corpus/mt940/basic_valid.mt940").read_bytes(),
        ParseContext(file_name="basic_valid.mt940"),
    )

    assert adapter.implementation_version == "0.0.20"
    assert result.account.id == "GB75TEST00000000000001"
    assert result.account.currency == "GBP"
    assert result.statement.id == "1"
    assert result.statement.sequence == "1"
    assert result.statement.opening_balance == Decimal("500.00")
    assert result.statement.closing_balance == Decimal("561.25")
    assert result.transactions[0].booking_date.isoformat() == "2026-09-15"
    assert result.transactions[0].value_date.isoformat() == "2026-09-15"
    assert result.transactions[0].amount == Decimal("-18.75")
    assert result.transactions[0].description == "Test materials"
    assert result.transactions[0].transaction_id is None
    assert result.transactions[0].reference == "MATERIAL"
    assert result.transactions[0].raw["parser_transaction_id"] == (
        "NTRFMATERIAL//SYNTH-BANK-1"
    )
