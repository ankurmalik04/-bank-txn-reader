"""The optional OFX adapter must enforce the same source financial evidence."""

import runpy
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from bankparser.errors import ParseError
from bankparser.parsers.base import ParseContext
from bankparser.parsers.ofx.bankstatementparser import BankStatementParserOfxAdapter

BASIC = Path("corpus/ofx/basic_valid.ofx").read_bytes()
CASES = runpy.run_path("tests/ofx_cases.py")["cases"]()


def adapter_for(records, summary):
    class Backend:
        def __init__(self, path):
            pass

        def parse(self):
            return SimpleNamespace(to_dict=lambda orient: records)

        def get_summaries(self):
            return [summary]

    adapter = BankStatementParserOfxAdapter.__new__(BankStatementParserOfxAdapter)
    adapter._parser_class = Backend
    return adapter


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["expected"].get("reject")], ids=lambda c: c["name"]
)
def test_bad_source_never_reaches_alternative_backend(case):
    pytest.importorskip("defusedxml")
    adapter = adapter_for([], {})

    def forbidden(*args, **kwargs):
        pytest.fail("invalid source reached optional backend")

    adapter._parser_class = forbidden
    with pytest.raises(ParseError):
        adapter.parse(case["data"], ParseContext())


@pytest.mark.parametrize(
    "mutation",
    [
        "amount",
        "identity",
        "order",
        "currency",
        "account",
        "closing",
        "opening",
        "date",
        "count",
    ],
)
def test_backend_cannot_change_financial_evidence(mutation):
    records = [
        {
            "date": "20260915",
            "amount": Decimal("-18.75"),
            "currency": "GBP",
            "transaction_id": "SYNTH-OFX-1",
        },
        {
            "date": "20260916",
            "amount": Decimal(80),
            "currency": "GBP",
            "transaction_id": "SYNTH-OFX-2",
        },
    ]
    summary = {
        "account_id": "GB75TEST00000000000001",
        "currency": "GBP",
        "closing_balance": None,
    }
    if mutation == "amount":
        records[0]["amount"] += 1
        records[1]["amount"] -= 1
    elif mutation == "identity":
        records[0]["transaction_id"] = "WRONG"
    elif mutation == "order":
        records.reverse()
    elif mutation == "currency":
        summary["currency"] = "USD"
    elif mutation == "account":
        summary["account_id"] = "OTHER"
    elif mutation == "closing":
        summary["closing_balance"] = Decimal(999)
    elif mutation == "opening":
        summary["opening_balance"] = Decimal(500)
    elif mutation == "date":
        records[0]["date"] = "20260916"
    elif mutation == "count":
        records.pop()
    adapter = adapter_for(deepcopy(records), summary)
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC, ParseContext())
    assert caught.value.code == (
        "TRANSACTION_COUNT_MISMATCH" if mutation == "count" else "OFX_BACKEND_MISMATCH"
    )


def test_record_currency_conflict_is_rejected():
    records = [
        {
            "date": "20260915",
            "amount": Decimal("-18.75"),
            "currency": "USD",
            "transaction_id": "SYNTH-OFX-1",
        },
        {
            "date": "20260916",
            "amount": Decimal(80),
            "currency": "GBP",
            "transaction_id": "SYNTH-OFX-2",
        },
    ]
    adapter = adapter_for(
        records, {"account_id": "GB75TEST00000000000001", "currency": "GBP"}
    )
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC, ParseContext())
    assert caught.value.code == "OFX_BACKEND_MISMATCH"


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if not c["expected"].get("reject")],
    ids=lambda c: c["name"],
)
def test_real_alternative_backend_preserves_source_financial_fields(case):
    pytest.importorskip("bankstatementparser")
    from bankparser import parse
    from bankparser.parsers.ofx.source import read_source

    result = parse(case["data"], implementation="bankstatementparser")
    expected = read_source(case["data"]).canonical
    assert result.account == expected.account
    assert result.statement == expected.statement
    assert [
        (t.amount, t.transaction_id, t.currency, t.booking_date)
        for t in result.transactions
    ] == [
        (t.amount, t.transaction_id, t.currency, t.booking_date)
        for t in expected.transactions
    ]
