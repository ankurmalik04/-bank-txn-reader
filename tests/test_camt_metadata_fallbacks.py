"""CAMT metadata regressions using only the independently invented corpus."""

import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from bankparser import parse
from bankparser.serialization import to_primitive

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install the camt extra for metadata regressions",
)
NS = "{urn:iso:std:iso:20022:tech:xsd:camt.053.001.02}"
SOURCE = Path("corpus/camt053/basic_valid.camt053.xml")


def case(index=0):
    root = ET.fromstring(SOURCE.read_bytes())
    entry = root.findall(f".//{NS}Ntry")[index]
    detail = entry.find(f"{NS}NtryDtls/{NS}TxDtls")
    return root, entry, detail


def add(parent, tag, value):
    ET.SubElement(parent, NS + tag).text = value


def remove(parent, tag):
    for node in parent.findall(NS + tag):
        parent.remove(node)


def assert_financial_fields_unchanged(result):
    """Check metadata-only edits against the independently authored golden."""
    expected = json.loads(SOURCE.with_name("basic_valid.expected.json").read_text())
    actual = to_primitive(result)
    assert actual["account"] == expected["account"]
    assert actual["statement"] == expected["statement"]
    fields = ("booking_date", "value_date", "amount", "currency", "transaction_id")
    assert [
        {field: transaction[field] for field in fields}
        for transaction in actual["transactions"]
    ] == [
        {field: transaction[field] for field in fields}
        for transaction in expected["transactions"]
    ]
    assert result.validation.status == "passed"


@pytest.mark.parametrize(
    ("narrative", "detail_info", "entry_info", "expected"),
    [
        (None, None, "Synthetic entry information", "Synthetic entry information"),
        (None, "Synthetic detail information", "Entry", "Synthetic detail information"),
        ("  ", "Synthetic detail information", "Entry", "Synthetic detail information"),
        ("Keep remittance", "Detail", "Entry", "Keep remittance"),
    ],
)
def test_description_uses_additional_information_only_without_remittance(
    narrative, detail_info, entry_info, expected
):
    root, entry, detail = case()
    remove(detail, "RmtInf")
    if narrative is not None:
        add(ET.SubElement(detail, NS + "RmtInf"), "Ustrd", narrative)
    if detail_info is not None:
        add(detail, "AddtlTxInf", detail_info)
    add(entry, "AddtlNtryInf", entry_info)
    result = parse(ET.tostring(root))
    assert result.transactions[0].description == expected
    assert len(result.transactions) == 2
    assert result.validation.status == "passed"
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize(
    ("e2e", "narrative", "detail_ref", "expected"),
    [
        (None, None, None, "SYNTH-ENTRY-REF"),
        (None, None, "SYNTH-DETAIL-REF", "SYNTH-DETAIL-REF"),
        (None, "Keep backend narrative", None, "Keep backend narrative"),
        ("SYNTH-E2E-KEPT", "Narrative", "DETAIL", "SYNTH-E2E-KEPT"),
    ],
)
def test_entry_reference_fallback_preserves_existing_priority(
    e2e, narrative, detail_ref, expected
):
    root, entry, detail = case()
    remove(detail, "Refs")
    refs = ET.SubElement(detail, NS + "Refs")
    if e2e is not None:
        add(refs, "EndToEndId", e2e)
    if detail_ref is not None:
        add(refs, "AcctSvcrRef", detail_ref)
    remove(detail, "RmtInf")
    if narrative is not None:
        add(ET.SubElement(detail, NS + "RmtInf"), "Ustrd", narrative)
    add(entry, "AcctSvcrRef", "SYNTH-ENTRY-REF")
    result = parse(ET.tostring(root))
    transaction = result.transactions[0]
    assert transaction.reference == expected
    assert transaction.raw["account_servicer_reference"] == (
        detail_ref or "SYNTH-ENTRY-REF"
    )
    assert result.validation.status == "passed"
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("account_kind", ["IBAN", "other"])
def test_return_uses_one_party_for_name_and_account(index, account_kind):
    root, _, detail = case(index)
    remove(detail, "RltdPties")
    parties = ET.SubElement(detail, NS + "RltdPties")
    # Reverse the usual party role while leaving the booked movement unchanged.
    role = "Dbtr" if index == 0 else "Cdtr"
    add(ET.SubElement(parties, NS + role), "Nm", "Synthetic original party")
    identity = ET.SubElement(ET.SubElement(parties, NS + role + "Acct"), NS + "Id")
    if account_kind == "IBAN":
        add(identity, "IBAN", "GB48TEST00000000000002")
    else:
        add(ET.SubElement(identity, NS + "Othr"), "Id", "SYNTH-OTHER-ACCOUNT")
    result = parse(ET.tostring(root))
    counterparty = result.transactions[index].counterparty
    assert counterparty.name == "Synthetic original party"
    assert counterparty.account_id == (
        "GB48TEST00000000000002" if account_kind == "IBAN" else "SYNTH-OTHER-ACCOUNT"
    )
    assert counterparty.iban == (
        "GB48TEST00000000000002" if account_kind == "IBAN" else None
    )
    assert result.validation.status == "passed"
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("index", [0, 1])
def test_unnamed_preferred_account_does_not_borrow_other_partys_name(index):
    root, _, detail = case(index)
    remove(detail, "RltdPties")
    parties = ET.SubElement(detail, NS + "RltdPties")
    preferred = "Cdtr" if index == 0 else "Dbtr"
    other = "Dbtr" if index == 0 else "Cdtr"
    identity = ET.SubElement(ET.SubElement(parties, NS + preferred + "Acct"), NS + "Id")
    add(identity, "IBAN", "GB48TEST00000000000002")
    add(ET.SubElement(parties, NS + other), "Nm", "Different synthetic party")
    result = parse(ET.tostring(root))
    assert result.transactions[index].counterparty.name is None
    assert (
        result.transactions[index].counterparty.account_id == "GB48TEST00000000000002"
    )
    assert result.transactions[index].counterparty.iban == "GB48TEST00000000000002"
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("index", [0, 1])
def test_zero_movement_uses_reported_direction_to_select_party(index):
    root, entry, detail = case(index)
    entry.find(NS + "Amt").text = "0.00"
    remove(detail, "RltdPties")
    parties = ET.SubElement(detail, NS + "RltdPties")
    for role in ("Cdtr", "Dbtr"):
        add(ET.SubElement(parties, NS + role), "Nm", "Synthetic " + role)
        identity = ET.SubElement(ET.SubElement(parties, NS + role + "Acct"), NS + "Id")
        add(ET.SubElement(identity, NS + "Othr"), "Id", "SYNTH-" + role)
    # Adjust the closing balance to conserve the otherwise unchanged statement.
    closing = root.findall(f".//{NS}Bal")[1].find(NS + "Amt")
    closing.text = "580.00" if index == 0 else "481.25"
    result = parse(ET.tostring(root))
    role = "Cdtr" if index == 0 else "Dbtr"
    assert result.transactions[index].counterparty.name == "Synthetic " + role
    assert result.transactions[index].counterparty.account_id == "SYNTH-" + role
    assert result.validation.status == "passed"


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("preferred_fields", ["both", "name", "account"])
def test_preferred_party_is_never_completed_from_the_other_party(
    index, preferred_fields
):
    root, _, detail = case(index)
    remove(detail, "RltdPties")
    parties = ET.SubElement(detail, NS + "RltdPties")
    preferred = "Cdtr" if index == 0 else "Dbtr"
    other = "Dbtr" if index == 0 else "Cdtr"
    for role in (preferred, other):
        if role == other or preferred_fields in ("both", "name"):
            add(ET.SubElement(parties, NS + role), "Nm", "Synthetic " + role)
        if role == other or preferred_fields in ("both", "account"):
            identity = ET.SubElement(
                ET.SubElement(parties, NS + role + "Acct"), NS + "Id"
            )
            add(ET.SubElement(identity, NS + "Othr"), "Id", "SYNTH-" + role)
    result = parse(ET.tostring(root))
    counterparty = result.transactions[index].counterparty
    assert counterparty.name == (
        "Synthetic " + preferred if preferred_fields != "account" else None
    )
    assert counterparty.account_id == (
        "SYNTH-" + preferred if preferred_fields != "name" else None
    )
    assert counterparty.iban is None
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("available", ["none", "name", "account"])
def test_missing_counterparty_fields_remain_missing(index, available):
    root, _, detail = case(index)
    remove(detail, "RltdPties")
    parties = ET.SubElement(detail, NS + "RltdPties")
    # Only the opposite role is present; missing attributes must not be invented.
    role = "Dbtr" if index == 0 else "Cdtr"
    if available == "name":
        add(ET.SubElement(parties, NS + role), "Nm", "Synthetic fallback party")
    elif available == "account":
        identity = ET.SubElement(ET.SubElement(parties, NS + role + "Acct"), NS + "Id")
        add(identity, "IBAN", "GB48TEST00000000000002")
    result = parse(ET.tostring(root))
    counterparty = result.transactions[index].counterparty
    assert counterparty.name == (
        "Synthetic fallback party" if available == "name" else None
    )
    assert counterparty.account_id == (
        "GB48TEST00000000000002" if available == "account" else None
    )
    assert counterparty.iban == counterparty.account_id
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("detail_info", [None, "", " \t "])
def test_blank_additional_information_uses_entry_fallback(detail_info):
    root, entry, detail = case()
    remove(detail, "RmtInf")
    if detail_info is not None:
        add(detail, "AddtlTxInf", detail_info)
    add(entry, "AddtlNtryInf", "  Synthetic entry text  ")
    result = parse(ET.tostring(root))
    assert result.transactions[0].description == "Synthetic entry text"
    assert_financial_fields_unchanged(result)


def test_multiline_remittance_keeps_priority_and_order():
    root, entry, detail = case()
    remove(detail, "RmtInf")
    remittance = ET.SubElement(detail, NS + "RmtInf")
    for text in (" First synthetic line ", "  ", "Second synthetic line"):
        add(remittance, "Ustrd", text)
    add(detail, "AddtlTxInf", "Detail fallback")
    add(entry, "AddtlNtryInf", "Entry fallback")
    result = parse(ET.tostring(root))
    assert result.transactions[0].description == (
        "First synthetic line\nSecond synthetic line"
    )
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("index", [0, 1])
def test_absent_description_and_references_are_not_invented(index):
    root, _, detail = case(index)
    remove(detail, "RmtInf")
    remove(detail, "Refs")
    result = parse(ET.tostring(root))
    transaction = result.transactions[index]
    assert transaction.description is None
    assert transaction.reference is None
    assert transaction.transaction_id is None
    assert "account_servicer_reference" not in transaction.raw
    assert_financial_fields_unchanged(result)


@pytest.mark.parametrize("e2e", [None, "", "  ", "NOTPROVIDED"])
def test_unavailable_end_to_end_id_allows_entry_reference_fallback(e2e):
    root, entry, detail = case()
    remove(detail, "RmtInf")
    remove(detail, "Refs")
    if e2e is not None:
        add(ET.SubElement(detail, NS + "Refs"), "EndToEndId", e2e)
    add(entry, "AcctSvcrRef", "SYNTH-ENTRY-ONLY")
    result = parse(ET.tostring(root))
    assert result.transactions[0].reference == "SYNTH-ENTRY-ONLY"
    assert (
        result.transactions[0].raw["account_servicer_reference"] == "SYNTH-ENTRY-ONLY"
    )
    assert_financial_fields_unchanged(result)
