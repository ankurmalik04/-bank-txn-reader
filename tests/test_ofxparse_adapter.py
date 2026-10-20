"""Independent evaluation expectations and production OFX safety boundaries."""

from __future__ import annotations

import importlib.util
import runpy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from bankparser import ParseError, implementations, parse
from bankparser.errors import ParserDependencyError
from bankparser.parsers.base import ParseContext
from bankparser.parsers.ofx import OfxParseAdapter
from bankparser.parsers.ofx import ofxparse as adapter_module

PROBE = runpy.run_path("tests/ofx_cases.py")
BASIC = Path("corpus/ofx/basic_valid.ofx").read_bytes()
requires_ofx = pytest.mark.skipif(
    importlib.util.find_spec("ofxparse") is None,
    reason="install the ofx extra",
)


@requires_ofx
@pytest.mark.parametrize("case", PROBE["cases"](), ids=lambda case: case["name"])
def test_production_adapter_meets_evaluation_expectation(case, canonical_core):
    if case["expected"].get("reject"):
        with pytest.raises(ParseError) as caught:
            parse(case["data"])
        assert caught.value.location is not None
    else:
        result = parse(case["data"])
        assert result.source.implementation == "ofxparse"
        assert result.source.implementation_version == "0.21"
        assert PROBE["check"](canonical_core(result), case["expected"])


def test_ofx_registry_and_missing_dependencies(monkeypatch):
    assert implementations("ofx") == ("bankstatementparser", "ofxparse")

    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(adapter_module.importlib, "import_module", missing)
    with pytest.raises(ParserDependencyError, match=r"\[ofx\]"):
        OfxParseAdapter()


@requires_ofx
@pytest.mark.parametrize("xml", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_ofx_line_endings_preserve_canonical_facts(xml, newline, canonical_core):
    body = PROBE["xml_document"](BASIC.decode()) if xml else BASIC.decode()
    source = body.replace("\n", newline).encode()
    golden = next(case for case in PROBE["cases"]() if case["name"] == "corpus_bank_sgml")
    assert PROBE["check"](canonical_core(parse(source)), golden["expected"])


@requires_ofx
@pytest.mark.parametrize(
    "before,after,code",
    [
        (b"</STMTRS>", b"<TRNAMT>100\n</STMTRS>", "INVALID_OFX_STRUCTURE"),
        (b"</STMTRS>", b"<BALAMT>100\n</STMTRS>", "INVALID_OFX_STRUCTURE"),
        (
            b"</OFX>",
            b"<BILLPAYMSGSRSV1></BILLPAYMSGSRSV1></OFX>",
            "UNSUPPORTED_OFX_SCOPE",
        ),
        (b"<TRNAMT>-18.75", b"<TRNAMT>-18.75\n<TRNAMT>-99", "INVALID_OFX_STRUCTURE"),
        (
            b"<MEMO>Test materials",
            b"<MEMO>Test materials\n<MEMO>Other",
            "INVALID_OFX_STRUCTURE",
        ),
        (b"<CURDEF>GBP", b"<CURDEF>GBP\n<CURDEF>USD", "INVALID_OFX_STRUCTURE"),
        (b"<CURDEF>GBP", b"<CURDEF>GB", "INVALID_CURRENCY"),
        (b"<DTPOSTED>20260915000000", b"<DTPOSTED>20260915256000", "INVALID_DATE"),
        (b"<DTPOSTED>20260915000000", b"<DTPOSTED>20260915JUNK", "INVALID_DATE"),
        (
            b"<DTPOSTED>20260915000000",
            b"<DTPOSTED>20260915000000[+99:X]",
            "INVALID_DATE",
        ),
        (b"<DTPOSTED>20260915000000\n", b"", "INVALID_OFX_STRUCTURE"),
        (b"</BANKTRANLIST>", b"</LEDGERBAL>", "INVALID_OFX_STRUCTURE"),
        (b"</OFX>", b"", "INVALID_OFX_STRUCTURE"),
        (b"</OFX>", b"</OFX>trailing", "INVALID_OFX_STRUCTURE"),
        (b"<BANKTRANLIST>", b"<BANKTRANLIST>unexpected", "INVALID_OFX_STRUCTURE"),
        (b"<STMTTRN>", b"<STMTTRN attr='bad'>", "INVALID_OFX_STRUCTURE"),
        (b"DATA:OFXSGML", b"DATA:OFXSGML\nDATA:OFXSGML", "INVALID_OFX_STRUCTURE"),
        (b"VERSION:102", b"VERSION:999", "UNSUPPORTED_OFX_PROFILE"),
        (b"SECURITY:NONE", b"SECURITY:TYPE1", "UNSUPPORTED_OFX_PROFILE"),
        (b"<NAME>Synthetic Workshop", b"<NAME>&unknown;", "INVALID_OFX_STRUCTURE"),
        (b"<NAME>Synthetic Workshop", b"<NAME>&#0;", "INVALID_OFX_STRUCTURE"),
        (b"</STMTRS>", b"<INVSTMTRS></INVSTMTRS></STMTRS>", "UNSUPPORTED_OFX_SCOPE"),
        (
            b"</STMTRS>",
            b"<CCACCTFROM><ACCTID>Other</CCACCTFROM></STMTRS>",
            "INVALID_OFX_STRUCTURE",
        ),
        (
            b"</STMTRS>",
            b"<LEDGERBAL><BALAMT>0\n<DTASOF>20260916\n</LEDGERBAL></STMTRS>",
            "INVALID_OFX_STRUCTURE",
        ),
        (
            b"</STMTRS>",
            b"</STMTRS><AVAILBAL><BALAMT>0\n<DTASOF>20260916\n</AVAILBAL>",
            "INVALID_OFX_STRUCTURE",
        ),
        (b"<FITID>SYNTH-OFX-1", b"<FITID>", "INVALID_OFX_STRUCTURE"),
        (
            b"<TRNAMT>-18.75",
            b"<TRNAMT><VALUE>-18.75</VALUE></TRNAMT>",
            "INVALID_OFX_STRUCTURE",
        ),
    ],
)
def test_invalid_source_is_rejected_before_backend(monkeypatch, before, after, code):
    adapter = OfxParseAdapter()

    def must_not_parse(*args, **kwargs):
        pytest.fail("invalid source reached ofxparse")

    monkeypatch.setattr(adapter._parser, "parse", must_not_parse)
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC.replace(before, after, 1), ParseContext())
    assert caught.value.code == code


@requires_ofx
@pytest.mark.parametrize(
    "markup",
    [
        '<OFX xmlns="urn:ofx">',
        '<OFX attr="unsupported">',
        "<OFX>text",
        "<OFX><NAME><CHILD>mixed</CHILD></NAME>",
    ],
)
def test_xml_profile_rejects_namespaces_attributes_and_mixed_fields(markup):
    xml = PROBE["xml_document"](BASIC.decode()).replace("<OFX>", markup, 1)
    with pytest.raises(ParseError):
        parse(xml.encode())


@requires_ofx
@pytest.mark.parametrize("xml", [False, True])
def test_excessive_nesting_is_rejected(xml):
    body = PROBE["xml_document"](BASIC.decode()) if xml else BASIC.decode()
    body = body.replace("<OFX>", "<OFX>" + "<X>" * 70, 1)
    body = body.replace("</OFX>", "</X>" * 70 + "</OFX>")
    with pytest.raises(ParseError) as caught:
        parse(body.encode())
    assert caught.value.code == "INVALID_OFX_STRUCTURE"


@requires_ofx
def test_local_dates_raw_evidence_and_empty_optional_text():
    source = BASIC.replace(b"20260915000000", b"20260915003000.123[+2:CET]", 1)
    source = source.replace(
        b"<MEMO>Test materials", b"<MEMO>\n<DTUSER>20260914230000[-5:EST]"
    )
    result = parse(source)
    tx = result.transactions[0]
    assert tx.booking_date == date(2026, 9, 15)
    assert tx.value_date is None
    assert tx.description == "Synthetic Workshop"
    assert tx.raw["source_fields"]["DTPOSTED"] == "20260915003000.123[+2:CET]"
    assert tx.raw["source_fields"]["DTUSER"] == "20260914230000[-5:EST]"
    assert tx.raw["source_path"] == "STMTRS/BANKTRANLIST/STMTTRN[1]"
    assert (
        parse(BASIC.replace(b"<NAME>Synthetic Workshop", b"<NAME>", 1))
        .transactions[0]
        .description
        == "Test materials"
    )


@requires_ofx
def test_sgml_entities_bare_ampersands_latin1_and_closing_date_fallback():
    source = BASIC.replace(
        b"<MEMO>Test materials", b"<MEMO>Caf\xe9 &amp; cake & tea &#8364;"
    )
    source = source.replace(b"CHARSET:1252", b"CHARSET:8859-1").replace(
        b"<DTEND>20260916000000\n", b""
    )
    result = parse(source)
    assert result.transactions[0].description == "Café & cake & tea €"
    assert result.statement.end_date == date(2026, 9, 16)


@requires_ofx
def test_available_balance_is_not_a_closing_ledger_balance():
    source = BASIC.replace(b"LEDGERBAL", b"AVAILBAL")
    result = parse(source)
    assert result.statement.closing_balance is None
    assert "MISSING_CLOSING_BALANCE" in {w.code for w in result.warnings}


@requires_ofx
@pytest.mark.parametrize("version", [b"103", b"160"])
def test_supported_sgml_header_versions(version, canonical_core):
    assert canonical_core(
        parse(BASIC.replace(b"VERSION:102", b"VERSION:" + version))
    ) == canonical_core(parse(BASIC))


@requires_ofx
def test_statement_period_and_ledger_fallback_retain_local_day():
    source = BASIC.replace(b"20260914000000", b"20260914003000[+2:CET]")
    source = source.replace(b"20260916000000", b"20260916233000[-5:EST]")
    result = parse(source)
    assert result.statement.start_date == date(2026, 9, 14)
    assert result.statement.end_date == date(2026, 9, 16)
    assert result.transactions[1].booking_date == date(2026, 9, 16)
    source = source.replace(b"<DTEND>20260916233000[-5:EST]\n", b"")
    assert parse(source).statement.end_date == date(2026, 9, 16)


@requires_ofx
def test_response_warning_is_exposed():
    source = BASIC.replace(
        b"<TRNUID>0", b"<TRNUID>0\n<STATUS><CODE>0\n<SEVERITY>WARN\n</STATUS>"
    )
    assert "OFX_RESPONSE_WARNING" in {w.code for w in parse(source).warnings}


def fake_output():
    statement = SimpleNamespace(
        transactions=[
            SimpleNamespace(id="SYNTH-OFX-1", amount=Decimal("-18.75")),
            SimpleNamespace(id="SYNTH-OFX-2", amount=Decimal("80.00")),
        ],
        currency="gbp",
        balance=Decimal("561.25"),
        discarded_entries=[],
        warnings=[],
    )
    account = SimpleNamespace(
        account_id="GB75TEST00000000000001", statement=statement, warnings=[]
    )
    return SimpleNamespace(accounts=[account])


@requires_ofx
@pytest.mark.parametrize(
    "mutation,code",
    [
        (lambda result: result.accounts.clear(), "OFX_BACKEND_MISMATCH"),
        (
            lambda result: result.accounts[0].statement.transactions.pop(),
            "TRANSACTION_COUNT_MISMATCH",
        ),
        (
            lambda result: result.accounts[0].statement.discarded_entries.append(
                "lost"
            ),
            "INCOMPLETE_OUTPUT",
        ),
        (
            lambda result: setattr(result.accounts[0], "account_id", "OTHER"),
            "OFX_BACKEND_MISMATCH",
        ),
        (
            lambda result: setattr(result.accounts[0].statement, "currency", "usd"),
            "OFX_BACKEND_MISMATCH",
        ),
        (
            lambda result: setattr(result.accounts[0].statement, "balance", Decimal(0)),
            "OFX_BACKEND_MISMATCH",
        ),
        (
            lambda result: setattr(
                result.accounts[0].statement.transactions[0], "id", "OTHER"
            ),
            "OFX_BACKEND_MISMATCH",
        ),
        (
            lambda result: setattr(
                result.accounts[0].statement.transactions[0], "amount", Decimal(0)
            ),
            "OFX_BACKEND_MISMATCH",
        ),
        (
            lambda result: setattr(result.accounts[0], "statement", None),
            "OFX_BACKEND_ERROR",
        ),
    ],
)
def test_backend_cannot_silently_change_financial_evidence(monkeypatch, mutation, code):
    adapter = OfxParseAdapter()
    output = fake_output()
    mutation(output)
    monkeypatch.setattr(adapter._parser, "parse", lambda *args, **kwargs: output)
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC, ParseContext())
    assert caught.value.code == code


@requires_ofx
def test_backend_failures_and_diagnostics_are_structured(monkeypatch):
    adapter = OfxParseAdapter()

    def broken(*args, **kwargs):
        raise ValueError("upstream failed")

    monkeypatch.setattr(adapter._parser, "parse", broken)
    with pytest.raises(ParseError) as caught:
        adapter.parse(BASIC, ParseContext())
    assert caught.value.code == "OFX_BACKEND_ERROR"
    output = fake_output()
    output.accounts[0].warnings.append("account warning")
    output.accounts[0].statement.warnings.append("statement warning")
    monkeypatch.setattr(adapter._parser, "parse", lambda *args, **kwargs: output)
    warnings = adapter.parse(BASIC, ParseContext()).warnings
    assert [w.message for w in warnings if w.code == "OFX_BACKEND_WARNING"] == [
        "account warning",
        "statement warning",
    ]


@requires_ofx
def test_concurrent_bank_card_and_timezone_parses():
    sources = [
        BASIC,
        Path("corpus/ofx/basic_valid.qfx").read_bytes(),
        BASIC.replace(b"20260915000000", b"20260915233000[-5:EST]", 1),
    ] * 10
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(parse, sources))
    assert [result.account.currency for result in results] == ["GBP", "USD", "GBP"] * 10
    assert all(
        result.transactions[0].booking_date == date(2026, 9, 15) for result in results
    )


@requires_ofx
def test_basic_output_matches_legacy_backend(canonical_core):
    pytest.importorskip("bankstatementparser")
    assert canonical_core(parse(BASIC)) == canonical_core(
        parse(BASIC, implementation="bankstatementparser")
    )
