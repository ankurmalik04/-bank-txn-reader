from __future__ import annotations

import sys
from decimal import Decimal
from types import ModuleType
from xml.etree import ElementTree

from bankparser.parsers.base import ParseContext
from bankparser.parsers.camt053.bankstatementparser import (
    BankStatementParserCamt053Adapter,
)


class FakeFrame:
    def __init__(self, records):
        self._records = records

    def to_dict(self, orient: str):
        assert orient == "records"
        return self._records


class FakeCamtParser:
    @classmethod
    def from_bytes(cls, data: bytes, *, source_name: str):
        assert data == b"camt bytes"
        assert source_name == "statement.xml"
        return cls()

    def __init__(self) -> None:
        self.tree = ElementTree.fromstring(
            """
            <Document><BkToCstmrStmt><Stmt>
              <Id>CAMT-STMT-001</Id><ElctrncSeqNb>1</ElctrncSeqNb>
              <Acct><Id><IBAN>GB75TEST00000000000001</IBAN></Id></Acct>
              <Ntry><Amt Ccy="GBP">25.50</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-10-02</Dt></BookgDt><ValDt><Dt>2026-10-02</Dt></ValDt><Sts>BOOK</Sts><NtryDtls><TxDtls><Refs><EndToEndId>E2E-001</EndToEndId><AcctSvcrRef>ASR-001</AcctSvcrRef></Refs><RmtInf><Ustrd>Coffee</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
            </Stmt></BkToCstmrStmt></Document>
            """
        )

    def get_transactions(self):
        return FakeFrame(
            [
                {
                    "Amount": Decimal("-25.50"),
                    "Currency": "GBP",
                    "DrCr": "DBIT",
                    "Debtor": None,
                    "Creditor": "Coffee Shop",
                    "Reference": "BANK-001",
                    "EndToEndId": "E2E-001",
                    "AcctSvcrRef": "ASR-001",
                    "ValDt": "2026-10-02",
                    "BookgDt": "2026-10-02T12:00:00Z",
                    "AccountId": "GB75TEST00000000000001",
                }
            ]
        )

    def get_account_balances(self):
        return FakeFrame(
            [
                {"Code": "OPBD", "Date": "2026-10-01"},
                {"Code": "CLBD", "Date": "2026-10-03"},
            ]
        )

    def get_summaries(self):
        return [
            {
                "account_id": "GB75TEST00000000000001",
                "currency": "GBP",
                "statement_id": "CAMT-STMT-001",
                "opening_balance": Decimal("1000.00"),
                "closing_balance": Decimal("974.50"),
            }
        ]


def test_camt053_adapter_maps_normalized_output(monkeypatch) -> None:
    package = ModuleType("bankstatementparser")
    package.__version__ = "0.0.20"
    module = ModuleType("bankstatementparser.camt_parser")
    module.CamtParser = FakeCamtParser
    monkeypatch.setitem(sys.modules, "bankstatementparser", package)
    monkeypatch.setitem(sys.modules, "bankstatementparser.camt_parser", module)

    adapter = BankStatementParserCamt053Adapter()
    result = adapter.parse(b"camt bytes", ParseContext("statement.xml"))

    assert adapter.implementation_version == "0.0.20"
    assert result.account.id == "GB75TEST00000000000001"
    assert result.account.iban == "GB75TEST00000000000001"
    assert result.account.currency == "GBP"
    assert result.statement.id == "CAMT-STMT-001"
    assert result.statement.sequence == "1"
    assert result.statement.start_date.isoformat() == "2026-10-01"
    assert result.statement.end_date.isoformat() == "2026-10-03"
    assert result.transactions[0].amount == Decimal("-25.50")
    assert result.transactions[0].booking_date.isoformat() == "2026-10-02"
    assert result.transactions[0].value_date.isoformat() == "2026-10-02"
    assert result.transactions[0].counterparty.name == "Coffee Shop"
    assert result.transactions[0].reference == "E2E-001"
    assert result.transactions[0].description == "Coffee"
