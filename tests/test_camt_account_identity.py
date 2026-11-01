"""Reject ambiguous statement accounts before backend identity selection."""

import importlib.util
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as E

import pytest

from bankparser import ParseError, parse
from bankparser.parsers.camt053.bankstatementparser import _validate_source


def statement():
    root = E.fromstring(Path("corpus/camt053/basic_valid.camt053.xml").read_bytes())
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    return root.find(".//Stmt")


@pytest.mark.parametrize("different", [False, True])
def test_duplicate_account_is_rejected(different):
    node = statement()
    account = deepcopy(node.find("Acct"))
    if different:
        account.find("Id/IBAN").text = "OTHER-ACCOUNT"
    node.append(account)
    with pytest.raises(ParseError) as caught:
        _validate_source(node)
    assert caught.value.code == "AMBIGUOUS_CAMT_ACCOUNT"
    assert caught.value.location == "Stmt/Acct"


@pytest.mark.parametrize("path", ["Id", "Id/IBAN", "Id/Othr", "Id/Othr/Id"])
def test_repeated_identity_choice_is_rejected(path):
    node = statement()
    account = node.find("Acct")
    if "Othr" in path:
        account.find("Id").clear()
        E.SubElement(E.SubElement(account.find("Id"), "Othr"), "Id").text = "ACCOUNT-1"
    parent_path, _, tag = path.rpartition("/")
    parent = account.find(parent_path) if parent_path else account
    parent.append(deepcopy(parent.find(tag)))
    with pytest.raises(ParseError) as caught:
        _validate_source(node)
    assert caught.value.code == "AMBIGUOUS_CAMT_ACCOUNT"
    assert caught.value.location == "Stmt/Acct/" + path


def test_iban_and_other_identity_are_rejected_together():
    node = statement()
    E.SubElement(E.SubElement(node.find("Acct/Id"), "Othr"), "Id").text = "ACCOUNT-2"
    with pytest.raises(ParseError, match="identity choice"):
        _validate_source(node)


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None, reason="camt extra"
)
@pytest.mark.parametrize("identity", ["iban", "other", "missing"])
def test_single_account_identity_still_parses(identity):
    node = statement()
    if identity != "iban":
        node.find("Acct/Id").clear()
        if identity == "other":
            E.SubElement(
                E.SubElement(node.find("Acct/Id"), "Othr"), "Id"
            ).text = "ACCOUNT-1"
    root = E.Element("Document", xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    E.SubElement(root, "BkToCstmrStmt").append(node)
    result = parse(E.tostring(root))
    assert len(result.transactions) == 2
    assert (
        result.account.id
        == {"iban": "GB75TEST00000000000001", "other": "ACCOUNT-1", "missing": None}[
            identity
        ]
    )
    check = next(c for c in result.validation.checks if c.code == "ACCOUNT_IDENTITY")
    assert check.status == ("skipped" if identity == "missing" else "passed")


def test_missing_account_container_is_rejected():
    node = statement()
    node.remove(node.find("Acct"))
    with pytest.raises(ParseError) as caught:
        _validate_source(node)
    assert caught.value.code == "AMBIGUOUS_CAMT_ACCOUNT"
    assert caught.value.location == "Stmt/Acct"
