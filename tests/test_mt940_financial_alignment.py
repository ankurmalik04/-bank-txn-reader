"""Ordered financial evidence must match before source metadata enrichment."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import ParseError
from bankparser.parsers.base import ParseContext

BASIC = Path("corpus/mt940/basic_valid.mt940").read_bytes()


@pytest.mark.parametrize("backend", ["wolph", "bankstatementparser"])
@pytest.mark.parametrize(
    "mutation",
    ["order", "amount", "date", "reference", "account", "balance", "currency"],
)
def test_backend_corruption_is_rejected(backend, mutation, monkeypatch):
    if backend == "wolph":
        from bankparser.parsers.mt940.wolph import WolphMt940Adapter

        adapter = WolphMt940Adapter()
        original = adapter._mt940.parse_statements

        def altered(*args, **kwargs):
            statements = original(*args, **kwargs)
            native = statements[0]
            if mutation == "order":
                native.transactions.reverse()
            elif mutation == "amount":
                native.transactions[0].data["amount"].amount += 1
                native.transactions[1].data["amount"].amount -= 1
            elif mutation == "date":
                native.transactions[0].data["date"] = date(2026, 9, 16)
            elif mutation == "reference":
                native.transactions[0].data["customer_reference"] = "OTHER"
            elif mutation == "account":
                native.data["account_identification"] = "OTHER"
            elif mutation == "balance":
                native.data["final_closing_balance"].amount.amount += 1
            elif mutation == "currency":
                native.transactions[0].data["amount"].currency = "USD"
            return statements

        monkeypatch.setattr(adapter._mt940, "parse_statements", altered)
    else:
        pytest.importorskip("bankstatementparser")
        from bankparser.parsers.mt940.bankstatementparser import (
            BankStatementParserMt940Adapter,
        )

        adapter = BankStatementParserMt940Adapter()
        original = adapter._parser_class

        class Altered(original):
            def parse(self):
                frame = super().parse()
                if mutation == "order":
                    frame = frame.iloc[::-1]
                elif mutation == "amount":
                    frame.loc[0, "amount"] += 1
                    frame.loc[1, "amount"] -= 1
                elif mutation == "date":
                    frame.loc[0, "date"] = "2026-09-16"
                elif mutation == "reference":
                    frame.loc[0, "transaction_id"] = "NTRFOTHER"
                elif mutation == "currency":
                    frame.loc[0, "currency"] = "USD"
                return frame

            def get_summaries(self):
                summaries = super().get_summaries()
                if mutation == "account":
                    summaries[0]["account_id"] = "OTHER"
                elif mutation == "balance":
                    summaries[0]["closing_balance"] += 1
                return summaries

        adapter._parser_class = Altered
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC, ParseContext())
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"
    assert caught.value.location


@pytest.mark.parametrize(
    "mark,expected",
    [("D", -12), ("C", 12), ("RC", -12), ("RD", 12), ("EC", 12), ("ED", -12)],
)
def test_source_amount_direction_and_currency(mark, expected):
    from bankparser.parsers.mt940.source import source_fields

    _, rows = source_fields(
        f":60F:C260914GBP500,00\n:61:260915{mark}12,00NTRFREF\n".encode()
    )
    assert rows[0]["amount"] == Decimal(expected)
    assert rows[0]["currency"] == "GBP"
    assert rows[0]["value_date"] == date(2026, 9, 15)


@pytest.mark.parametrize("backend", ["wolph", "bankstatementparser"])
def test_legitimate_repeated_transactions_remain_distinct(backend):
    if backend == "bankstatementparser":
        pytest.importorskip("bankstatementparser")
    from bankparser import parse

    data = b":20:REPEAT\n:25:ACCT\n:28C:1/1\n:60F:C260914GBP0,00\n"
    data += b":61:260915C1,00NTRFREF\n:86:Repeated\n" * 2
    data += b":62F:C260915GBP2,00\n"
    result = parse(data, implementation=backend)
    assert len(result.transactions) == 2
    assert [t.amount for t in result.transactions] == [Decimal(1), Decimal(1)]
