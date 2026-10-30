"""Regression cases for the three P0 review findings."""

import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import ParseError, parse
from bankparser.models import Account, Statement, Transaction
from bankparser.validation import validate

CAMT = Path("corpus/camt053/basic_valid.camt053.xml")
backend = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="requires camt extra",
)


def checks(*transactions, start=date(2026, 9, 14), end=date(2026, 9, 16)):
    return {
        c.code: c
        for c in validate(
            Account(id="SYNTH", currency="GBP"),
            Statement(start_date=start, end_date=end),
            tuple(transactions),
        ).checks
    }


def transaction(booking=date(2026, 9, 15), value=date(2026, 9, 15), currency="GBP"):
    return Transaction(booking, value, Decimal(1), currency)


@pytest.mark.parametrize("currency", [None, "", "  "])
def test_missing_transaction_currency_is_incomplete_even_with_account_currency(
    currency,
):
    result = checks(transaction(), transaction(currency=currency))
    assert result["CURRENCY_CONSISTENCY"].status == "passed"
    assert result["TRANSACTION_CURRENCIES"].status == "skipped"
    assert "1" in result["TRANSACTION_CURRENCIES"].message


def test_missing_currency_does_not_hide_known_currency_conflict():
    result = checks(transaction(currency=None), transaction(currency="EUR"))
    assert result["CURRENCY_CONSISTENCY"].status == "failed"
    assert result["TRANSACTION_CURRENCIES"].status == "skipped"


@pytest.mark.parametrize("day", [date(2026, 9, 14), date(2026, 9, 16)])
def test_inclusive_booking_and_value_boundaries(day):
    result = checks(transaction(day, day))
    assert result["TRANSACTION_BOOKING_DATES"].status == "passed"
    assert result["TRANSACTION_VALUE_DATES"].status == "passed"


@pytest.mark.parametrize("day", [date(2026, 9, 13), date(2026, 9, 17)])
def test_value_date_boundary_exception_is_reviewable_not_failed(day):
    result = checks(transaction(value=day))
    assert result["TRANSACTION_BOOKING_DATES"].status == "passed"
    assert result["TRANSACTION_VALUE_DATES"].status == "skipped"
    assert "exceptions require review" in result["TRANSACTION_VALUE_DATES"].message
    result = checks(transaction(booking=day))
    assert result["TRANSACTION_BOOKING_DATES"].status == "failed"


def test_missing_dates_and_period_bounds_do_not_pass_completeness():
    result = checks(transaction(None, None))
    assert result["TRANSACTION_BOOKING_DATES"].status == "skipped"
    assert result["TRANSACTION_VALUE_DATES"].status == "skipped"
    result = checks(transaction(), start=None)
    assert result["TRANSACTION_BOOKING_DATES"].status == "skipped"
    result = checks(transaction(booking=date(2026, 9, 17)), start=None)
    assert result["TRANSACTION_BOOKING_DATES"].status == "failed"


def test_empty_activity_has_no_missing_transaction_fields():
    result = checks()
    for code in [
        "TRANSACTION_BOOKING_DATES",
        "TRANSACTION_VALUE_DATES",
        "TRANSACTION_CURRENCIES",
    ]:
        assert result[code].status == "passed"


@backend
def test_backend_reordering_is_rejected_before_metadata_enrichment(monkeypatch):
    from bankstatementparser.camt_parser import CamtParser

    original = CamtParser.get_transactions

    def reordered(self):
        return original(self).iloc[::-1].reset_index(drop=True)

    monkeypatch.setattr(CamtParser, "get_transactions", reordered)
    with pytest.raises(ParseError) as caught:
        parse(CAMT)
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"


@backend
@pytest.mark.parametrize(
    "field,value",
    [
        ("Amount", Decimal(-19)),
        ("Currency", "EUR"),
        ("DrCr", "CRDT"),
        ("BookgDt", "2026-09-14"),
        ("ValDt", "2026-09-14"),
        ("AccountId", "WRONG-ACCOUNT"),
        ("EndToEndId", "WRONG-E2E"),
        ("AcctSvcrRef", "WRONG-BANK-REF"),
    ],
)
def test_backend_financial_and_identity_changes_are_rejected(monkeypatch, field, value):
    from bankstatementparser.camt_parser import CamtParser

    original = CamtParser.get_transactions

    def changed(self):
        result = original(self)
        result.loc[0, field] = value
        return result

    monkeypatch.setattr(CamtParser, "get_transactions", changed)
    with pytest.raises(ParseError) as caught:
        parse(CAMT)
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"


@backend
def test_ambiguous_repeated_source_keys_are_rejected_even_with_different_metadata():
    import copy
    import xml.etree.ElementTree as E

    root = E.fromstring(CAMT.read_bytes())
    statement = root.find(".//{*}Stmt")
    entries = statement.findall("{*}Ntry")
    duplicate = copy.deepcopy(entries[0])
    duplicate.find(
        ".//{*}Ustrd"
    ).text = "Different metadata, indistinguishable financial identity"
    statement.remove(entries[1])
    statement.append(duplicate)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "AMBIGUOUS_TRANSACTION_ALIGNMENT"


@backend
def test_repeated_source_keys_are_accepted_when_enrichment_is_invariant():
    import copy
    import xml.etree.ElementTree as E

    root = E.fromstring(CAMT.read_bytes().replace(b"561.25", b"462.50"))
    statement = root.find(".//{*}Stmt")
    entries = statement.findall("{*}Ntry")
    duplicate = copy.deepcopy(entries[0])
    statement.remove(entries[1])
    statement.append(duplicate)

    result = parse(E.tostring(root))

    assert result.validation.status == "passed"
    assert result.statement.closing_balance == Decimal("462.50")
    assert [tx.amount for tx in result.transactions] == [Decimal("-18.75")] * 2
    assert len(result.transactions) == 2
    assert result.transactions[0].description == result.transactions[1].description
    assert result.transactions[0].reference == result.transactions[1].reference
    assert result.transactions[0].counterparty == result.transactions[1].counterparty
    assert (
        result.transactions[0].raw["source_path"]
        != result.transactions[1].raw["source_path"]
    )


@backend
def test_repeated_source_keys_reject_conflicting_backend_enrichment(monkeypatch):
    import copy
    import xml.etree.ElementTree as E

    from bankstatementparser.camt_parser import CamtParser

    root = E.fromstring(CAMT.read_bytes())
    statement = root.find(".//{*}Stmt")
    entries = statement.findall("{*}Ntry")
    duplicate = copy.deepcopy(entries[0])
    statement.remove(entries[1])
    statement.append(duplicate)
    original = CamtParser.get_transactions

    def conflicting(self):
        frame = original(self)
        frame.loc[1, "Reference"] = "DIFFERENT-BACKEND-REFERENCE"
        return frame

    monkeypatch.setattr(CamtParser, "get_transactions", conflicting)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "AMBIGUOUS_TRANSACTION_ALIGNMENT"


@backend
@pytest.mark.parametrize("mismatched_index", [1, 2])
@pytest.mark.parametrize("source_metadata_conflict", [False, True])
def test_financial_mismatch_precedes_repeated_enrichment_ambiguity(
    monkeypatch, mismatched_index, source_metadata_conflict
):
    import copy
    import xml.etree.ElementTree as E

    from bankstatementparser.camt_parser import CamtParser

    root = E.fromstring(CAMT.read_bytes().replace(b"561.25", b"542.50"))
    statement = root.find(".//{*}Stmt")
    entries = statement.findall("{*}Ntry")
    duplicate = copy.deepcopy(entries[0])
    if source_metadata_conflict:
        duplicate.find(".//{*}Ustrd").text = "Conflicting source metadata"
    statement.insert(list(statement).index(entries[1]), duplicate)
    original = CamtParser.get_transactions

    def conflicting(self):
        frame = original(self)
        frame.loc[1, "Reference"] = "DIFFERENT-BACKEND-REFERENCE"
        frame.loc[mismatched_index, "Amount"] = Decimal("-19.00")
        return frame

    monkeypatch.setattr(CamtParser, "get_transactions", conflicting)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"
    assert (
        caught.value.location == f"Stmt/Ntry[{mismatched_index + 1}]/NtryDtls/TxDtls[1]"
    )


@backend
def test_unique_equal_amount_records_use_references_to_detect_reordering(monkeypatch):
    from bankstatementparser.camt_parser import CamtParser

    original = CamtParser.get_transactions
    source = (
        CAMT.read_bytes()
        .replace(b"80.00", b"18.75")
        .replace(b"<CdtDbtInd>CRDT</CdtDbtInd>", b"<CdtDbtInd>DBIT</CdtDbtInd>")
        .replace(b"2026-09-16</Dt></BookgDt>", b"2026-09-15</Dt></BookgDt>")
        .replace(b"2026-09-16</Dt></ValDt>", b"2026-09-15</Dt></ValDt>")
    )

    def reordered(self):
        return original(self).iloc[::-1].reset_index(drop=True)

    monkeypatch.setattr(CamtParser, "get_transactions", reordered)
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"


@backend
def test_batched_details_align_on_booked_amounts_and_own_references(monkeypatch):
    import copy
    import xml.etree.ElementTree as E

    from bankstatementparser.camt_parser import CamtParser

    root = E.fromstring(CAMT.read_bytes())
    ns = root.tag.split("}")[0] + "}"
    entry = root.find(".//{*}Ntry")
    parent = entry.find("{*}NtryDtls")
    detail = parent.find("{*}TxDtls")
    other = copy.deepcopy(detail)
    for node, amount, ref, narrative in [
        (detail, "8.00", "BATCH-A", "Part A"),
        (other, "10.75", "BATCH-B", "Part B"),
    ]:
        E.SubElement(node, ns + "Amt", {"Ccy": "GBP"}).text = amount
        node.find(".//{*}EndToEndId").text = ref
        node.find(".//{*}AcctSvcrRef").text = ref + "-BANK"
        node.find(".//{*}Ustrd").text = narrative
    parent.append(other)
    source = E.tostring(root)
    result = parse(source)
    assert [t.amount for t in result.transactions] == [
        Decimal(-8),
        Decimal("-10.75"),
        Decimal(80),
    ]
    assert [t.description for t in result.transactions[:2]] == ["Part A", "Part B"]
    assert [t.reference for t in result.transactions[:2]] == ["BATCH-A", "BATCH-B"]
    assert result.validation.status == "passed"
    original = CamtParser.get_transactions

    def reordered(self):
        frame = original(self)
        return frame.iloc[[1, 0, 2]].reset_index(drop=True)

    monkeypatch.setattr(CamtParser, "get_transactions", reordered)
    with pytest.raises(ParseError) as caught:
        parse(source)
    assert caught.value.code == "TRANSACTION_ALIGNMENT_MISMATCH"


@backend
def test_value_date_exceptions_warn_and_strict_cli_rejects(tmp_path, capsys):
    import json

    from bankparser.cli import main

    source = tmp_path / "boundary.xml"
    source.write_bytes(
        CAMT.read_bytes().replace(
            b"<ValDt><Dt>2026-09-15</Dt></ValDt>",
            b"<ValDt><Dt>2026-10-01</Dt></ValDt>",
            1,
        )
    )
    assert main([str(source)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["validation"]["status"] == "warning"
    assert main([str(source), "--strict-validation"]) == 3
    output = json.loads(capsys.readouterr().out)
    assert (
        next(
            c
            for c in output["validation"]["checks"]
            if c["code"] == "TRANSACTION_VALUE_DATES"
        )["status"]
        == "skipped"
    )
