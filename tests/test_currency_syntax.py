"""Malformed nonblank currencies must never be import-ready."""

from dataclasses import fields, replace
from datetime import date
from decimal import Decimal

import pytest

from bankparser import ImportPolicy, ParseError, assess_import, parse
from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationResult,
)
from bankparser.validation import validate


@pytest.mark.parametrize("currency", ["USDD", "12A", "€", "ßP", "ＵＳＤ"])
def test_csv_rejects_invalid_source_currency(currency):
    data = f"Booking Date,Amount,Currency,Account\n2026-09-15,1.00,{currency},acct1\n".encode()
    with pytest.raises(ParseError) as caught:
        parse(data)
    assert caught.value.code == "INVALID_CURRENCY"
    assert caught.value.format == "csv"
    assert caught.value.record_index == 0
    assert caught.value.canonical_field == "transactions.currency"


def test_lowercase_csv_currency_is_normalized():
    parsed = parse(b"Booking Date,Amount,Currency,Account\n2026-09-15,1.00,usd,acct1\n")
    assert parsed.account.currency == parsed.transactions[0].currency == "USD"
    assert assess_import(parsed).status == "ready"


@pytest.mark.parametrize("field", ["account", "transaction", "opening", "closing"])
@pytest.mark.parametrize("currency", ["USDD", "12A", "ßP", " USD "])
def test_canonical_currency_check_cannot_be_overridden(field, currency):
    account = Account("acct1", currency=currency if field == "account" else None)
    statement = Statement(
        **(
            {field + "_balance_currency": currency}
            if field in {"opening", "closing"}
            else {}
        )
    )
    transactions = (
        Transaction(
            date(2026, 9, 15),
            None,
            Decimal(1),
            currency if field == "transaction" else None,
        ),
    )
    report = validate(account, statement, transactions)
    check = next(c for c in report.checks if c.code == "CURRENCY_FORMAT")
    assert check.status == "failed"
    policy = ImportPolicy()
    policy = replace(
        policy,
        **{
            f.name: "ignore"
            for f in fields(policy)
            if getattr(policy, f.name) in ("ignore", "review", "block")
        },
    )
    result = ParseResult(
        "1.1",
        SourceMetadata("csv", "synthetic", None, "test"),
        account,
        statement,
        transactions,
        ValidationResult("passed"),
    )
    assessed = assess_import(result, policy)
    assert assessed.status == "not-ready"
    assert any(r.source_code == "CURRENCY_FORMAT" for r in assessed.reasons)


@pytest.mark.parametrize("currency", [None, "", "   ", "USD", "usd"])
def test_missing_currency_and_valid_syntax_remain_separate(currency):
    report = validate(Account(currency=currency), Statement(), ())
    assert (
        next(c for c in report.checks if c.code == "CURRENCY_FORMAT").status == "passed"
    )


@pytest.mark.parametrize("currency", ["USDD", "12A", "ßP", "ＵＳＤ"])
def test_camt_rejects_invalid_currency_before_normalization(currency):
    from bankparser.parsers.camt053.bankstatementparser import _currency

    with pytest.raises(ParseError) as caught:
        _currency(currency)
    assert caught.value.code == "INVALID_CURRENCY"
    assert _currency("gbp") == "GBP"


@pytest.mark.parametrize("currency", ["USDD", "12A", "ßP"])
def test_ofx_rejects_invalid_currency_before_normalization(currency):
    from pathlib import Path

    from bankparser.parsers.ofx.source import read_source

    source = Path("corpus/ofx/basic_valid.ofx").read_bytes()
    source = source.replace(b"<CURDEF>GBP", ("<CURDEF>" + currency).encode())
    with pytest.raises(ParseError) as caught:
        read_source(source)
    assert caught.value.code == "INVALID_CURRENCY"
