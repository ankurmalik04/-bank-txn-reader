from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from bankparser.parsers.base import ParseContext
from bankparser.parsers.ofx.bankstatementparser import BankStatementParserOfxAdapter

OFX_BYTES = b"""<OFX>
<BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>GBP
<BANKACCTFROM><ACCTID>ACCOUNT-1</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20261001000000
<DTEND>20261003000000
<STMTTRN><DTPOSTED>20261002000000<TRNAMT>-25.50<FITID>TX-1</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL><BALAMT>974.50<DTASOF>20261003000000</LEDGERBAL>
</STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""


class FakeFrame:
    def to_dict(self, orient: str):
        assert orient == "records"
        return [
            {
                "date": "20261002",
                "description": "Coffee",
                "amount": Decimal("-25.50"),
                "currency": "GBP",
                "account_id": "ACCOUNT-1",
                "transaction_id": "TX-1",
                "transaction_type": "DEBIT",
            }
        ]


class FakeOfxParser:
    expected_bytes = OFX_BYTES

    def __init__(self, file_name: str | Path) -> None:
        path = Path(file_name)
        assert path.suffix == ".qfx"
        assert path.read_bytes() == self.expected_bytes

    def parse(self) -> FakeFrame:
        return FakeFrame()

    def get_summaries(self):
        return [
            {
                "account_id": "ACCOUNT-1",
                "currency": "GBP",
                "opening_balance": None,
                "closing_balance": None,
            }
        ]


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_ofx_adapter_maps_normalized_output_and_statement_tags(monkeypatch, newline) -> None:
    data = OFX_BYTES.replace(b"\n", newline)
    monkeypatch.setattr(FakeOfxParser, "expected_bytes", data)
    package = ModuleType("bankstatementparser")
    package.__version__ = "0.0.20"
    module = ModuleType("bankstatementparser.additional_parsers")
    module.OfxParser = FakeOfxParser

    monkeypatch.setitem(sys.modules, "bankstatementparser", package)
    monkeypatch.setitem(sys.modules, "bankstatementparser.additional_parsers", module)

    adapter = BankStatementParserOfxAdapter()
    result = adapter.parse(data, ParseContext("statement.qfx"))

    assert adapter.implementation_version == "0.0.20"
    assert result.account.id == "ACCOUNT-1"
    assert result.account.currency == "GBP"
    assert result.account.iban is None
    assert result.statement.start_date.isoformat() == "2026-10-01"
    assert result.statement.end_date.isoformat() == "2026-10-03"
    assert result.statement.opening_balance is None
    assert result.statement.closing_balance == Decimal("974.50")
    assert result.transactions[0].booking_date.isoformat() == "2026-10-02"
    assert result.transactions[0].value_date is None
    assert result.transactions[0].amount == Decimal("-25.50")
    assert result.transactions[0].transaction_id == "TX-1"
    assert result.transactions[0].raw["transaction_type"] == "DEBIT"
    assert [warning.code for warning in result.warnings] == [
        "MISSING_OPENING_BALANCE"
    ]
