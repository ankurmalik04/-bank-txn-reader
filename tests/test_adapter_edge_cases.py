from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from bankparser.errors import ParseError, ParserDependencyError
from bankparser.parsers.camt053 import bankstatementparser as camt
from bankparser.parsers.csv import bankstatementparser as csv_backend
from bankparser.parsers.csv import native as csv_adapter
from bankparser.parsers.mt940 import bankstatementparser as mt940_alt
from bankparser.parsers.mt940 import wolph
from bankparser.parsers.ofx import bankstatementparser as ofx
from bankparser.parsers.ofx import ofxparse
from bankparser.version import __version__


@pytest.mark.parametrize(
    ("module", "adapter_class", "extra"),
    [
        (camt, camt.BankStatementParserCamt053Adapter, "camt"),
        (csv_backend, csv_backend.BankStatementParserCsvAdapter, "alternative"),
        (mt940_alt, mt940_alt.BankStatementParserMt940Adapter, "alternative"),
        (ofx, ofx.BankStatementParserOfxAdapter, "alternative"),
        (wolph, wolph.WolphMt940Adapter, None),
        (ofxparse, ofxparse.OfxParseAdapter, "ofx"),
    ],
)
def test_missing_parser_dependency_is_explicit(
    monkeypatch, module, adapter_class, extra
) -> None:
    def missing(name: str):
        raise ImportError(name)

    monkeypatch.setattr(module.importlib, "import_module", missing)
    with pytest.raises(ParserDependencyError) as caught:
        adapter_class()
    suffix = f"[{extra}]" if extra else ""
    message = str(caught.value)
    assert caught.value.code == "MISSING_DEPENDENCY"
    assert "GitHub release" in message
    assert f'python -m pip install "./bankparser_runtime-{__version__}-py3-none-any.whl{suffix}"' in message
    assert f'python -m pip install ".{suffix}"' in message


def test_camt_helper_semantics() -> None:
    assert camt._optional_decimal(None) is None
    assert camt._optional_decimal("12.30") == Decimal("12.30")
    assert camt._optional_decimal("bad") is None
    assert camt._optional_decimal(Decimal("NaN")) is None

    instant = datetime(2026, 10, 2, 12, 30, tzinfo=timezone.utc)
    day = date(2026, 10, 2)
    assert camt._optional_date(instant) == day
    assert camt._optional_date(day) == day
    assert camt._optional_date(None) is None
    assert camt._optional_date("2026-10-02T12:30:00") == day
    with pytest.raises(ParseError, match="invalid date"):
        camt._optional_date("not-a-date")

    assert camt._meaningful_reference(None) is None
    assert camt._meaningful_reference("NOTPROVIDED") is None
    assert camt._meaningful_reference(" REF-1 ") == "REF-1"
    assert camt._currency(" gbp ") == "GBP"
    assert camt._currency(None) is None

    assert camt._element_text(None, "./Id") is None

    tree = ElementTree.fromstring("<Document><Stmt><Id>S-1</Id></Stmt></Document>")
    statement = tree.find(".//Stmt")
    assert camt._source_transactions(statement) == []
    assert camt._element_text(statement, "./Id") == "S-1"
    assert camt._element_text(statement, "./Missing") is None

    records = [{"Code": "OPBD", "Date": "2026-10-01"}]
    assert camt._balance_date(records, "OPBD") == date(2026, 10, 1)
    assert camt._balance_date(records, "CLBD") is None


def test_camt_transaction_fallbacks() -> None:
    credit = camt._map_transaction(
        {
            "Amount": "25.00",
            "Debtor": "Employer",
            "Creditor": "Me",
            "Reference": "REF-1",
            "EndToEndId": "NOTPROVIDED",
            "BookgDt": "2026-10-02",
            "ValDt": "2026-10-03",
        },
        statement_currency="GBP",
        source={},
    )
    assert credit.counterparty.name == "Employer"
    assert credit.reference == "REF-1"
    assert credit.currency == "GBP"

    debit = camt._map_transaction(
        {
            "Amount": "-4.00",
            "Debtor": "Me",
            "Creditor": "Coffee Shop",
            "AcctSvcrRef": "ASR-1",
        },
        statement_currency=None,
        source={},
    )
    assert debit.counterparty.name == "Coffee Shop"
    assert debit.reference == "ASR-1"
    assert debit.currency is None
    with pytest.raises(ParseError, match="invalid amount"):
        camt._map_transaction({"Amount": "bad"}, statement_currency="GBP", source={})


def test_csv_header_semantics_and_value_helpers() -> None:
    from bankparser import CsvOptions

    columns = csv_adapter._columns(
        ("Booking Date", "Value Date", "Date", "Transaction ID", "Reference")
    )
    assert columns == {
        "booking_date": "Booking Date",
        "value_date": "Value Date",
        "date": "Date",
        "transaction_id": "Transaction ID",
        "reference": "Reference",
    }
    assert csv_adapter._amount("10.25", CsvOptions(), 2, "Amount") == Decimal("10.25")
    for text in ("bad", "NaN", "Infinity"):
        with pytest.raises(ParseError):
            csv_adapter._amount(text, CsvOptions(), 2, "Amount")


def test_csv_date_parser_is_conservative() -> None:
    expected = date(2026, 10, 2)
    assert csv_adapter._optional_csv_date("") is None
    assert csv_adapter._optional_csv_date("2026-10-02") == expected
    assert csv_adapter._optional_csv_date("2026/10/02") == expected
    assert csv_adapter._optional_csv_date("02.10.2026") == expected
    assert csv_adapter._optional_csv_date("13/10/2026") == date(2026, 10, 13)
    assert csv_adapter._optional_csv_date("10/13/2026") == date(2026, 10, 13)
    assert csv_adapter._optional_csv_date("02/10/2026") is None
    assert csv_adapter._optional_csv_date("31/02/2026") is None
    assert csv_adapter._optional_csv_date("garbage") is None
    assert csv_adapter._date_from_parts("2026", "02", "31") is None
    assert csv_adapter._date_from_parts("year", "02", "01") is None


def test_csv_transaction_preserves_unknown_identity() -> None:
    from bankparser import parse

    result = parse(
        b"Value Date,Amount,Native ID,Balance,Currency\n2026-10-02,10.00,NATIVE-1,110.00,GBP\n"
    )
    transaction = result.transactions[0]
    assert transaction.booking_date is None
    assert transaction.value_date == date(2026, 10, 2)
    assert transaction.reference is None
    assert transaction.transaction_id is None
    assert transaction.raw["source_fields"]["Native ID"] == "NATIVE-1"
    assert transaction.raw["source_balance"] == "110.00"


def test_mt940_alternative_helpers() -> None:
    opening, closing = mt940_alt._statement_boundary_dates(
        b":60F:C261001GBP100,00\n:62F:C261003GBP110,00\n"
    )
    assert opening == date(2026, 10, 1)
    assert closing == date(2026, 10, 3)
    assert mt940_alt._statement_boundary_dates(b"no balances") == (None, None)

    assert mt940_alt._optional_decimal(None) is None
    assert mt940_alt._optional_decimal("1.25") == Decimal("1.25")
    assert mt940_alt._optional_decimal("bad") is None
    assert mt940_alt._optional_decimal(Decimal("NaN")) is None
    with pytest.raises(ParseError, match="invalid amount"):
        mt940_alt._required_decimal("bad")

    expected = date(2026, 10, 2)
    instant = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    assert mt940_alt._optional_date(instant) == expected
    assert mt940_alt._optional_date(expected) == expected
    assert mt940_alt._optional_date(None) is None
    assert mt940_alt._optional_date("2026-10-02") == expected
    assert mt940_alt._optional_date("20261002") == expected
    with pytest.raises(ParseError, match="invalid date"):
        mt940_alt._optional_date("20261399")

    assert mt940_alt._statement_identity(None) == (None, None)
    assert mt940_alt._statement_identity("12") == ("12", None)
    assert mt940_alt._statement_identity("12/3") == ("12", "3")
    assert mt940_alt._currency(" gbp ") == "GBP"


def test_ofx_helpers_and_invalid_inputs() -> None:
    with pytest.raises(ParseError, match="0 statement scopes"):
        ofx._single_statement_scope("<OFX></OFX>")
    with pytest.raises(ParseError, match="2 statement scopes"):
        ofx._single_statement_scope("<STMTRS>a</STMTRS><CCSTMTRS>b</CCSTMTRS>")

    scope = "<STMTRS><CURDEF> GBP <LEDGERBAL><BALAMT>10.00</LEDGERBAL></STMTRS>"
    assert ofx._tag_value(scope, "CURDEF") == "GBP"
    assert ofx._tag_value(scope, "MISSING") is None
    assert ofx._container_tag_value(scope, "LEDGERBAL", "BALAMT") == "10.00"
    assert ofx._container_tag_value(scope, "MISSING", "BALAMT") is None

    assert ofx._optional_decimal(None) is None
    assert ofx._optional_decimal("10.00") == Decimal("10.00")
    assert ofx._optional_decimal("bad") is None
    assert ofx._optional_decimal(Decimal("Infinity")) is None
    with pytest.raises(ParseError, match="invalid amount"):
        ofx._required_decimal("bad")

    expected = date(2026, 10, 2)
    instant = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    assert ofx._optional_ofx_date(instant) == expected
    assert ofx._optional_ofx_date(expected) == expected
    assert ofx._optional_ofx_date(None) is None
    assert ofx._optional_ofx_date("20261002000000") == expected
    with pytest.raises(ParseError, match="invalid OFX date"):
        ofx._optional_ofx_date("2026")
    with pytest.raises(ParseError, match="invalid OFX date"):
        ofx._optional_ofx_date("20260231")


def test_wolph_value_helpers() -> None:
    native_amount = SimpleNamespace(amount=Decimal("1.25"), currency="GBP")
    assert wolph._amount(native_amount) == Decimal("1.25")
    assert wolph._amount(Decimal("2.50")) == Decimal("2.50")
    with pytest.raises(ParseError, match="invalid amount"):
        wolph._amount(SimpleNamespace(amount=Decimal("NaN")))

    balance = SimpleNamespace(amount=native_amount, date=date(2026, 10, 1))
    assert wolph._balance(balance) == Decimal("1.25")
    assert wolph._balance(None) is None
    assert wolph._balance(SimpleNamespace(amount=None)) is None
    assert wolph._balance_currency(balance) == "GBP"
    assert wolph._balance_date(balance) == date(2026, 10, 1)
    instant = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    assert wolph._date(instant) == date(2026, 10, 1)
    assert wolph._date("not-a-date") is None
    assert wolph._text("  x ") == "x"
    assert wolph._text(None) is None
