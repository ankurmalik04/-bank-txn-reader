"""Regressions for the financial correctness findings in the release review."""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import ParseError, parse
from bankparser.parsers.camt053 import bankstatementparser as camt
from bankparser.parsers.mt940 import bankstatementparser as mt940
from bankparser.parsers.ofx import bankstatementparser as ofx

requires_backend = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install all for real backend regressions",
)
CAMT = Path("corpus/camt053/basic_valid.camt053.xml")
OFX = Path("corpus/ofx/basic_valid.ofx")


def test_camt_guard_also_checks_nested_detail_magnitudes():
    from xml.etree import ElementTree

    statement = ElementTree.fromstring(
        "<Stmt><Ntry><Amt>18.75</Amt><Sts>BOOK</Sts><NtryDtls><TxDtls><AmtDtls><TxAmt><Amt>-18.75</Amt></TxAmt></AmtDtls></TxDtls></NtryDtls></Ntry></Stmt>"
    )
    with pytest.raises(ParseError) as caught:
        camt._validate_source(statement)
    assert caught.value.code == "SIGNED_CAMT_AMOUNT"
    assert caught.value.location == "Stmt//Amt[2]"


@requires_backend
def test_camt_preserves_conflicting_declared_account_currency():
    source = CAMT.read_bytes().replace(b"<Ccy>GBP</Ccy>", b"<Ccy>USD</Ccy>")
    result = parse(source)
    assert result.account.currency == "USD"
    assert {tx.currency for tx in result.transactions} == {"GBP"}
    assert result.statement.opening_balance_currency == "GBP"
    assert result.statement.closing_balance_currency == "GBP"
    checks = {check.code: check.status for check in result.validation.checks}
    assert checks["CURRENCY_CONSISTENCY"] == "failed"
    assert checks["BALANCE_RECONCILIATION"] == "passed"
    assert result.validation.status == "failed"


@requires_backend
@pytest.mark.parametrize("keep_narrative", [False, True])
def test_camt_mixed_missing_fields_use_only_real_fallbacks(keep_narrative):
    source = (
        CAMT.read_bytes()
        .replace(
            b"<Refs><AcctSvcrRef>SYNTH-BANK-1</AcctSvcrRef>"
            b"<EndToEndId>SYNTH-E2E-1</EndToEndId></Refs>",
            b"",
            1,
        )
        .replace(b"<BookgDt><Dt>2026-09-15</Dt></BookgDt>", b"", 1)
    )
    if not keep_narrative:
        source = source.replace(
            b"<RmtInf><Ustrd>Test materials</Ustrd></RmtInf>", b"", 1
        )
    result = parse(source)
    # Keep the existing documented backend-reference fallback when available.
    assert result.transactions[0].reference == (
        "Test materials" if keep_narrative else None
    )
    assert result.transactions[0].booking_date is None
    assert "end_to_end_id" not in result.transactions[0].raw
    assert "account_servicer_reference" not in result.transactions[0].raw
    assert result.transactions[1].reference == "SYNTH-E2E-2"
    assert result.validation.status == "warning"
    assert (
        next(
            c for c in result.validation.checks if c.code == "TRANSACTION_BOOKING_DATES"
        ).status
        == "skipped"
    )


@pytest.mark.parametrize("module", [camt, mt940, ofx])
@pytest.mark.parametrize("value", [float("nan"), Decimal("NaN"), Decimal("sNaN")])
def test_dataframe_missing_text_does_not_become_an_identifier(module, value):
    assert module._text(value) is None
    assert module._text("nan") == "nan"
    assert module._text("NaT") == "NaT"


@requires_backend
@pytest.mark.parametrize("module", [camt, mt940, ofx])
def test_dataframe_nullable_sentinels_are_missing_before_date_conversion(module):
    import pandas as pd

    date_parser = getattr(module, "_optional_date", ofx._optional_ofx_date)
    for value in (pd.NA, pd.NaT, float("nan")):
        assert module._text(value) is None
        assert date_parser(value) is None


@requires_backend
@pytest.mark.parametrize("status", ["PDNG", "INFO", "INVALID", ""])
@pytest.mark.parametrize("wrapped", [False, True])
def test_camt_rejects_unsupported_status_before_transaction_extraction(
    monkeypatch, status, wrapped
):
    from bankstatementparser.camt_parser import CamtParser

    def must_not_extract(*args, **kwargs):
        pytest.fail("unsupported entries reached backend transaction extraction")

    monkeypatch.setattr(CamtParser, "get_transactions", must_not_extract)
    replacement = f"<Sts><Cd>{status}</Cd></Sts>" if wrapped else f"<Sts>{status}</Sts>"
    source = CAMT.read_bytes().replace(
        b"<Sts><Cd>BOOK</Cd></Sts>", replacement.encode(), 1
    )
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "UNSUPPORTED_ENTRY_STATUS"
    assert caught.value.location == "Stmt/Ntry[1]/Sts"


@requires_backend
def test_camt_rejects_offsetting_pending_entries():
    pending = b"".join(
        f'<Ntry><Amt Ccy="GBP">10.00</Amt><CdtDbtInd>{direction}</CdtDbtInd>'
        "<Sts>PDNG</Sts></Ntry>".encode()
        for direction in ("CRDT", "DBIT")
    )
    with pytest.raises(ParseError) as caught:
        parse(CAMT.read_bytes().replace(b"</Stmt>", pending + b"</Stmt>"))
    assert caught.value.code == "UNSUPPORTED_ENTRY_STATUS"


@requires_backend
@pytest.mark.parametrize("amount", [b"1E+10000", b"1e-10000", b"NaN", b"Infinity"])
@pytest.mark.parametrize("original", [b">18.75<", b">500.00<"])
def test_camt_rejects_invalid_amounts_before_backend_arithmetic(
    monkeypatch, amount, original
):
    from bankstatementparser.camt_parser import CamtParser

    def must_not_extract(*args, **kwargs):
        pytest.fail("invalid monetary notation reached backend arithmetic")

    monkeypatch.setattr(CamtParser, "get_transactions", must_not_extract)
    source = CAMT.read_bytes().replace(original, b">" + amount + b"<", 1)
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "INVALID_AMOUNT"
    assert caught.value.location is not None


@requires_backend
@pytest.mark.parametrize("original", [b"<TRNAMT>-18.75", b"<BALAMT>561.25"])
def test_ofx_rejects_exponent_amounts_before_backend_arithmetic(monkeypatch, original):
    from bankstatementparser.additional_parsers import OfxParser

    def must_not_construct(*args, **kwargs):
        pytest.fail("invalid monetary notation reached the OFX backend")

    monkeypatch.setattr(OfxParser, "__init__", must_not_construct)
    tag = original.split(b">")[0] + b">"
    with pytest.raises(ParseError) as caught:
        parse(
            OFX.read_bytes().replace(original, tag + b"1E+10000", 1),
            implementation="bankstatementparser",
        )
    assert caught.value.code == "INVALID_AMOUNT"


@requires_backend
def test_camt_plain_large_amounts_preserve_exact_reconciliation():
    # The guard must not cap precision at the usual Decimal context's 28 digits.
    amount = b"123456789012345678901234567890.50"
    source = CAMT.read_bytes().replace(b">18.75<", b">" + amount + b"<", 1)
    source = source.replace(
        b'<Amt Ccy="GBP">561.25</Amt>\n        <CdtDbtInd>CRDT</CdtDbtInd>',
        b'<Amt Ccy="GBP">123456789012345678901234567310.50</Amt>\n'
        b"        <CdtDbtInd>DBIT</CdtDbtInd>",
    )
    result = parse(source)
    assert result.transactions[0].amount == Decimal(
        "-123456789012345678901234567890.50"
    )
    assert result.validation.status == "passed"


@requires_backend
@pytest.mark.parametrize("original", [b">18.75<", b">500.00<", b">561.25<"])
@pytest.mark.parametrize("amount", [b"-18.75", b"-0.00"])
def test_camt_rejects_signed_magnitudes_before_backend_arithmetic(
    monkeypatch, original, amount
):
    from bankstatementparser.camt_parser import CamtParser

    def must_not_extract(*args, **kwargs):
        pytest.fail("signed magnitude reached backend arithmetic")

    monkeypatch.setattr(CamtParser, "get_transactions", must_not_extract)
    source = CAMT.read_bytes().replace(original, b">" + amount + b"<", 1)
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "SIGNED_CAMT_AMOUNT"
    assert caught.value.location.startswith("Stmt//Amt[")


@requires_backend
def test_camt_signed_debit_cannot_become_a_reconciled_credit():
    source = (
        CAMT.read_bytes()
        .replace(b">18.75<", b">-18.75<", 1)
        .replace(b">561.25<", b">598.75<", 1)
    )
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "SIGNED_CAMT_AMOUNT"


@requires_backend
def test_reversed_camt_period_fails_validation_and_cli_keeps_json(tmp_path, capsys):
    import json

    from bankparser.cli import main

    source = CAMT.read_bytes().replace(
        b"<Dt>2026-09-14</Dt>", b"<Dt>2026-09-20</Dt>", 1
    )
    result = parse(source)
    assert result.validation.status == "failed"
    assert {c.code: c.status for c in result.validation.checks}[
        "STATEMENT_DATE_ORDER"
    ] == "failed"
    path = tmp_path / "reversed.xml"
    path.write_bytes(source)
    assert main([str(path)]) == 3
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["validation"]["status"] == "failed"


@requires_backend
def test_missing_camt_identity_is_incomplete_not_fabricated(tmp_path, capsys):
    import json

    from bankparser.cli import main

    source = CAMT.read_bytes().replace(b"GB75TEST00000000000001", b"")
    result = parse(source)
    assert result.account.id is None and result.account.iban is None
    assert result.validation.status == "warning"
    assert [w.code for w in result.warnings].count("MISSING_ACCOUNT_IDENTITY") == 1
    path = tmp_path / "missing-account.xml"
    path.write_bytes(source)
    assert main([str(path)]) == 0
    capsys.readouterr()
    assert main([str(path), "--strict-validation"]) == 3
    assert json.loads(capsys.readouterr().out)["validation"]["status"] == "warning"
