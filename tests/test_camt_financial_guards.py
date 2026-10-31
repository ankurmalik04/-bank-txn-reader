"""Independent synthetic CAMT direction, structure and entry-total regressions."""

import importlib.util
from copy import deepcopy
from decimal import Decimal, Inexact, localcontext
from pathlib import Path
from xml.etree import ElementTree as E

import pytest

from bankparser import ParseError, parse
from bankparser.parsers.camt053.bankstatementparser import _validate_source

FIXTURE = Path("corpus/camt053/basic_valid.camt053.xml")
SCHEMA_FIXTURES = Path(__file__).parent / "fixtures" / "camt053"
BATCH_FIXTURE = SCHEMA_FIXTURES / "valid_batch.camt053.xml"
backend = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="requires camt extra",
)


def document(path=FIXTURE):
    # Strip only this synthetic fixture's namespace for convenient mutations.
    root = E.fromstring(path.read_bytes())
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    root.set("xmlns", "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    return root


def extension_batch(root, index=0, amounts=("8.00", "10.75"), directions=(None, None)):
    # Nonstandard direct TxDtls/Amt and TxDtls/CdtDbtInd extensions.
    entry = root.findall(".//Stmt/Ntry")[index]
    parent = entry.find("NtryDtls")
    template = deepcopy(parent.find("TxDtls"))
    parent.clear()
    for i, (amount, direction) in enumerate(zip(amounts, directions)):
        detail = deepcopy(template)
        detail.find("Refs/EndToEndId").text = f"BATCH-{index}-{i}"
        E.SubElement(detail, "Amt", Ccy="GBP").text = amount
        if direction is not None:
            E.SubElement(detail, "CdtDbtInd").text = direction
        parent.append(detail)
    return entry


def assert_schema_valid(xml):
    etree = pytest.importorskip("lxml.etree")
    schema = etree.XMLSchema(etree.parse(str(SCHEMA_FIXTURES / "camt.053.001.02.xsd")))
    schema.assertValid(etree.fromstring(xml))


def test_standard_batch_fixture_is_schema_valid():
    assert_schema_valid(BATCH_FIXTURE.read_bytes())


def rejected(root, code, location):
    with pytest.raises(ParseError) as caught:
        _validate_source(root.find(".//Stmt"))
    assert caught.value.code == code
    assert caught.value.location == location


@pytest.mark.parametrize("scope", ["Bal", "Ntry", "Ntry/NtryDtls/TxDtls"])
@pytest.mark.parametrize("value", [None, "", "UNKNOWN", "crdt", " CRDT "])
def test_missing_or_invalid_directions(scope, value):
    root = document()
    node = root.find(".//Stmt/" + scope)
    old = node.find("CdtDbtInd")
    if old is not None:
        node.remove(old)
    if value is not None:
        E.SubElement(node, "CdtDbtInd").text = value
    # Detail omission intentionally inherits the entry direction.
    if scope.endswith("TxDtls") and value is None:
        _validate_source(root.find(".//Stmt"))
        return
    location = {
        "Bal": "Stmt/Bal[1]",
        "Ntry": "Stmt/Ntry[1]",
        "Ntry/NtryDtls/TxDtls": "Stmt/Ntry[1]/NtryDtls/TxDtls[1]",
    }[scope]
    rejected(root, "INVALID_CAMT_DIRECTION", location + "/CdtDbtInd")


@pytest.mark.parametrize("scope", ["Bal", "Ntry", "Ntry/NtryDtls/TxDtls"])
def test_duplicate_direction_is_rejected_even_when_equal(scope):
    root = document()
    node = root.find(".//Stmt/" + scope)
    if node.find("CdtDbtInd") is None:
        E.SubElement(node, "CdtDbtInd").text = "DBIT"
    node.append(deepcopy(node.find("CdtDbtInd")))
    location = {
        "Bal": "Stmt/Bal[1]",
        "Ntry": "Stmt/Ntry[1]",
        "Ntry/NtryDtls/TxDtls": "Stmt/Ntry[1]/NtryDtls/TxDtls[1]",
    }[scope]
    rejected(root, "INVALID_CAMT_DIRECTION", location + "/CdtDbtInd")


@pytest.mark.parametrize("scope", ["Bal", "Ntry"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_booked_amount(scope, duplicate):
    root = document()
    node = root.find(".//Stmt/" + scope)
    amount = node.find("Amt")
    if duplicate:
        node.append(deepcopy(amount))
    else:
        node.remove(amount)
    rejected(root, "INVALID_CAMT_AMOUNT_STRUCTURE", f"Stmt/{scope}[1]/Amt")


def test_single_detail_direction_conflict():
    root = document()
    E.SubElement(root.find(".//TxDtls"), "CdtDbtInd").text = "CRDT"
    rejected(
        root, "CAMT_DIRECTION_CONFLICT", "Stmt/Ntry[1]/NtryDtls/TxDtls[1]/CdtDbtInd"
    )


@pytest.mark.parametrize("balances", [False, True])
def test_bad_batch_rejected_without_relying_on_statement_balances(balances):
    root = document()
    extension_batch(root, amounts=("8", "9"))
    if not balances:
        statement = root.find(".//Stmt")
        for bal in statement.findall("Bal"):
            statement.remove(bal)
    rejected(root, "CAMT_BATCH_TOTAL_MISMATCH", "Stmt/Ntry[1]")


def test_offsetting_bad_batches_cannot_hide_in_global_reconciliation():
    root = document()
    extension_batch(root, 0, amounts=("8", "11.75"))  # Debit overstated by one.
    extension_batch(root, 1, amounts=("40", "41"))  # Credit overstated by one.
    rejected(root, "CAMT_BATCH_TOTAL_MISMATCH", "Stmt/Ntry[1]")


@pytest.mark.parametrize(
    "path",
    ["Amt", "AmtDtls/TxAmt/Amt", "AmtDtls/CntrValAmt/Amt", "AmtDtls/InstdAmt/Amt"],
)
def test_duplicate_detail_amount_is_never_silently_selected(path):
    root = document()
    entry = extension_batch(root)
    detail = entry.find("NtryDtls/TxDtls")
    if path != "Amt":
        parent = detail
        for name in path.split("/")[:-1]:
            parent = E.SubElement(parent, name)
        E.SubElement(parent, "Amt", Ccy="GBP").text = "8"
    else:
        parent = detail
    parent.append(deepcopy(detail.find(path)))
    rejected(
        root, "INVALID_CAMT_AMOUNT_STRUCTURE", "Stmt/Ntry[1]/NtryDtls/TxDtls[1]/" + path
    )


@pytest.mark.parametrize("kind", ["missing", "foreign", "instructed", "conflicting"])
def test_batch_requires_unambiguous_booked_currency_amount(kind):
    root = document()
    entry = extension_batch(root)
    detail = entry.find("NtryDtls/TxDtls")
    amount = detail.find("Amt")
    if kind == "missing":
        detail.remove(amount)
    elif kind == "foreign":
        amount.set("Ccy", "USD")
    elif kind == "instructed":
        detail.remove(amount)
        parent = E.SubElement(E.SubElement(detail, "AmtDtls"), "InstdAmt")
        parent.append(amount)
    else:
        parent = E.SubElement(E.SubElement(detail, "AmtDtls"), "TxAmt")
        E.SubElement(parent, "Amt", Ccy="GBP").text = "9"
    rejected(root, "TRANSACTION_ALIGNMENT_MISMATCH", "Stmt/Ntry[1]/NtryDtls/TxDtls[1]")


@backend
@pytest.mark.parametrize(
    "direction,amounts,expected,closing",
    [
        ("DBIT", ("8", "10.75"), [Decimal(-8), Decimal("-10.75")], "561.25"),
        ("CRDT", ("8", "10.75"), [Decimal(8), Decimal("10.75")], "598.75"),
        ("DBIT", ("0", "0"), [Decimal(0), Decimal(0)], "580.00"),
    ],
)
@pytest.mark.parametrize("reversal", [False, True])
@pytest.mark.parametrize("amount_kind", ["TxAmt", "CntrValAmt"])
def test_valid_batch_signs_zeros_and_reversals(
    direction, amounts, expected, closing, reversal, amount_kind
):
    root = document(BATCH_FIXTURE)
    entry = root.find(".//Stmt/Ntry")
    for detail, amount in zip(entry.findall("NtryDtls/TxDtls"), amounts):
        container = detail.find("AmtDtls/TxAmt")
        container.tag = amount_kind
        container.find("Amt").text = amount
    entry.find("CdtDbtInd").text = direction
    if amounts == ("0", "0"):
        entry.find("Amt").text = "0"
    entry.find("RvslInd").text = str(reversal).lower()
    root.findall(".//Stmt/Bal")[1].find("Amt").text = closing
    # Validate the actual input, including every sign/zero/reversal variant.
    xml = E.tostring(root)
    assert_schema_valid(xml)
    result = parse(xml)
    assert [t.amount for t in result.transactions[:2]] == expected
    assert [t.currency for t in result.transactions] == ["GBP"] * 3
    assert [t.reference for t in result.transactions[:2]] == ["BATCH-0-0", "BATCH-0-1"]
    assert result.statement.closing_balance == Decimal(closing)
    assert result.validation.status == "passed"


@backend
def test_extension_mixed_direction_batch_conserves_signed_not_unsigned_amounts():
    root = document()
    extension_batch(root, amounts=("20", "1.25"), directions=("DBIT", "CRDT"))
    result = parse(E.tostring(root))
    assert [t.amount for t in result.transactions] == [
        Decimal(-20),
        Decimal("1.25"),
        Decimal(80),
    ]
    assert result.validation.status == "passed"


@backend
def test_extension_foreign_and_instructed_amounts_are_separate_from_booked_amounts():
    root = document()
    entry = extension_batch(root)
    detail = entry.find("NtryDtls/TxDtls")
    detail.remove(detail.find("Amt"))
    amounts = E.SubElement(detail, "AmtDtls")
    for kind, value, currency in [
        ("TxAmt", "10", "USD"),
        ("CntrValAmt", "8", "GBP"),
        ("InstdAmt", "12", "EUR"),
    ]:
        E.SubElement(E.SubElement(amounts, kind), "Amt", Ccy=currency).text = value
    result = parse(E.tostring(root))
    first = result.transactions[0]
    assert first.amount == Decimal(-8)
    assert first.currency == "GBP"
    assert [(a["amount"], a["currency"]) for a in first.raw["amount_details"]] == [
        (Decimal(10), "USD"),
        (Decimal(8), "GBP"),
        (Decimal(12), "EUR"),
    ]
    assert first.raw["entry_amount"] == Decimal("18.75")
    assert first.raw["entry_direction"] == "DBIT"
    assert first.raw["entry_currency"] == "GBP"
    assert result.validation.status == "passed"


@backend
def test_extension_batch_arithmetic_is_exact_with_hostile_caller_context():
    root = document()
    entry = extension_batch(
        root, amounts=("123456789012345678901234567890.123456789", "0.000000001")
    )
    entry.find("Amt").text = "123456789012345678901234567890.123456790"
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = parse(E.tostring(root))
    assert result.transactions[0].amount == Decimal(
        "-123456789012345678901234567890.123456789"
    )
    assert result.transactions[1].amount == Decimal("-0.000000001")


@backend
def test_invalid_balance_direction_rejected_before_backend_extraction(monkeypatch):
    from bankstatementparser.camt_parser import CamtParser

    root = document()
    root.find(".//Bal/CdtDbtInd").text = "UNKNOWN"

    def must_not_extract(*args, **kwargs):
        pytest.fail("invalid source reached extraction")

    monkeypatch.setattr(CamtParser, "get_transactions", must_not_extract)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "INVALID_CAMT_DIRECTION"


@pytest.mark.parametrize(
    "path", ["AmtDtls", "AmtDtls/TxAmt", "AmtDtls/CntrValAmt", "AmtDtls/InstdAmt"]
)
def test_duplicate_amount_containers_are_rejected(path):
    root = document()
    detail = extension_batch(root).find("NtryDtls/TxDtls")
    parent = detail
    for name in path.split("/")[:-1]:
        parent = E.SubElement(parent, name)
    container = E.SubElement(parent, path.split("/")[-1])
    parent.append(deepcopy(container))
    rejected(
        root, "INVALID_CAMT_AMOUNT_STRUCTURE", "Stmt/Ntry[1]/NtryDtls/TxDtls[1]/" + path
    )


@pytest.mark.parametrize("kind", ["TxAmt", "CntrValAmt", "InstdAmt"])
def test_present_amount_container_requires_amount(kind):
    root = document()
    detail = extension_batch(root).find("NtryDtls/TxDtls")
    E.SubElement(E.SubElement(detail, "AmtDtls"), kind)
    rejected(
        root,
        "INVALID_CAMT_AMOUNT_STRUCTURE",
        "Stmt/Ntry[1]/NtryDtls/TxDtls[1]/AmtDtls/" + kind + "/Amt",
    )


@pytest.mark.parametrize("scope", ["Bal", "Ntry"])
def test_missing_booked_currency_is_rejected(scope):
    root = document()
    root.find(".//Stmt/" + scope + "/Amt").attrib.clear()
    if scope == "Ntry":
        account = root.find(".//Acct")
        account.remove(account.find("Ccy"))
    rejected(root, "MISSING_CAMT_CURRENCY", f"Stmt/{scope}[1]/Amt/@Ccy")


@backend
@pytest.mark.parametrize("balances", [False, True])
def test_batch_checks_run_before_backend_extraction(monkeypatch, balances):
    from bankstatementparser.camt_parser import CamtParser

    root = document()
    extension_batch(root, amounts=("8", "9"))
    if not balances:
        statement = root.find(".//Stmt")
        for bal in statement.findall("Bal"):
            statement.remove(bal)

    def must_not_extract(*args, **kwargs):
        pytest.fail("invalid batch reached backend extraction")

    monkeypatch.setattr(CamtParser, "get_transactions", must_not_extract)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "CAMT_BATCH_TOTAL_MISMATCH"
    assert caught.value.location == "Stmt/Ntry[1]"


@backend
def test_extension_valid_batch_without_balances_remains_parseable():
    root = document()
    extension_batch(root)
    statement = root.find(".//Stmt")
    for bal in statement.findall("Bal"):
        statement.remove(bal)
    result = parse(E.tostring(root))
    assert [t.amount for t in result.transactions] == [
        Decimal(-8),
        Decimal("-10.75"),
        Decimal(80),
    ]
    assert result.statement.opening_balance is None
    assert result.statement.closing_balance is None
    assert result.validation.status == "warning"


@backend
def test_single_detail_keeps_entry_amount_and_separate_foreign_metadata():
    root = document()
    detail = root.find(".//TxDtls")
    amounts = E.SubElement(detail, "AmtDtls")
    E.SubElement(E.SubElement(amounts, "TxAmt"), "Amt", Ccy="USD").text = "23"
    E.SubElement(E.SubElement(amounts, "InstdAmt"), "Amt", Ccy="EUR").text = "21"
    result = parse(E.tostring(root))
    assert result.transactions[0].amount == Decimal("-18.75")
    assert [a["amount"] for a in result.transactions[0].raw["amount_details"]] == [
        Decimal(23),
        Decimal(21),
    ]
    assert result.validation.status == "passed"


@backend
def test_extension_equal_amount_candidates_with_different_scales_are_unambiguous():
    root = document()
    detail = extension_batch(root).find("NtryDtls/TxDtls")
    amounts = E.SubElement(detail, "AmtDtls")
    E.SubElement(E.SubElement(amounts, "CntrValAmt"), "Amt", Ccy="GBP").text = "8.000"
    assert parse(E.tostring(root)).validation.status == "passed"


@backend
def test_debit_balances_remain_negative_and_are_not_reversed_twice():
    root = document()
    balances = root.findall(".//Stmt/Bal")
    for balance, amount in zip(balances, ["500", "438.75"]):
        balance.find("Amt").text = amount
        balance.find("CdtDbtInd").text = "DBIT"
    result = parse(E.tostring(root))
    assert result.statement.opening_balance == Decimal(-500)
    assert result.statement.closing_balance == Decimal("-438.75")
    assert result.validation.status == "passed"


@backend
def test_extension_source_amount_metadata_serializes_as_exact_decimal_strings():
    from bankparser.serialization import to_primitive

    root = document()
    extension_batch(root)
    raw = to_primitive(parse(E.tostring(root)))["transactions"][0]["raw"]
    assert raw["entry_amount"] == "18.75"
    assert raw["amount_details"][0] == {
        "source_path": "Stmt/Ntry[1]/NtryDtls/TxDtls[1]/Amt",
        "amount": "8.00",
        "currency": "GBP",
    }
