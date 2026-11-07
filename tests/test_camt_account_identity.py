"""Reject ambiguous statement accounts before backend identity selection."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as E

import pytest

from bankparser import ParseError, diagnostic_for_error, parse
from bankparser.cli import main
from bankparser.parsers.camt053.bankstatementparser import _validate_source
from bankparser.serialization import to_primitive


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


@pytest.mark.parametrize("currency", ["GBP", "EUR", "", "BADDD", "ßP"])
@pytest.mark.parametrize("empty", [False, True])
def test_repeated_account_currency_is_rejected_at_source(currency, empty):
    node = statement()
    if empty:
        for child in list(node):
            if child.tag in {"Ntry", "Bal"}:
                node.remove(child)
    E.SubElement(node.find("Acct"), "Ccy").text = currency
    with pytest.raises(ParseError) as caught:
        _validate_source(node)
    assert caught.value.code == "AMBIGUOUS_CAMT_ACCOUNT"
    assert caught.value.location == "Stmt/Acct/Ccy"


@pytest.mark.parametrize("currency", ["GBP", "EUR", "", "BADDD", "ßP"])
@pytest.mark.parametrize("empty", [False, True])
def test_repeated_account_currency_never_reaches_backend_extraction(
    currency, empty, monkeypatch
):
    module = pytest.importorskip("bankstatementparser.camt_parser")
    node = statement()
    if empty:
        for child in list(node):
            if child.tag in {"Ntry", "Bal"}:
                node.remove(child)
    E.SubElement(node.find("Acct"), "Ccy").text = currency
    root = E.Element("Document", xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    E.SubElement(root, "BkToCstmrStmt").append(node)

    def forbidden(*args, **kwargs):
        pytest.fail("ambiguous currency reached backend extraction")

    for method in ("get_transactions", "get_account_balances", "get_summaries"):
        monkeypatch.setattr(module.CamtParser, method, forbidden)
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "AMBIGUOUS_CAMT_ACCOUNT"
    assert caught.value.location == "Stmt/Acct/Ccy"


@pytest.mark.parametrize("policy", ["full", "redacted-diagnostic"])
def test_repeated_currency_cli_diagnostic(tmp_path, capsys, policy):
    pytest.importorskip("bankstatementparser")
    node = statement()
    E.SubElement(node.find("Acct"), "Ccy").text = "PRIVATE_CURRENCY"
    root = E.Element("Document", xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    E.SubElement(root, "BkToCstmrStmt").append(node)
    path = tmp_path / "PRIVATE_FILENAME.xml"
    path.write_bytes(E.tostring(root))
    assert main(["parse", str(path), "--json-errors", "--output-policy", policy]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    error = json.loads(output.err)["error"]
    assert error["code"] == "AMBIGUOUS_CAMT_ACCOUNT"
    assert error["diagnostic"]["code"] == "AMBIGUOUS_CAMT_ACCOUNT"
    if policy == "full":
        assert error["location"] == "Stmt/Acct/Ccy"
    assert "PRIVATE" not in output.err


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None, reason="camt extra"
)
@pytest.mark.parametrize("json_errors", [False, True])
def test_ambiguous_account_code_survives_redaction(tmp_path, capsys, json_errors):
    node = statement()
    account = deepcopy(node.find("Acct"))
    account.find("Id/IBAN").text = "PRIVATE_ACCOUNT_829174"
    node.append(account)
    root = E.Element("Document", xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    E.SubElement(root, "BkToCstmrStmt").append(node)
    data = E.tostring(root)
    with pytest.raises(ParseError) as caught:
        parse(data)
    expected = {
        "diagnostic_schema_version": "1",
        "code": "AMBIGUOUS_CAMT_ACCOUNT",
        "severity": "error",
        "format": "camt053",
        "canonical_field": None,
    }
    assert (
        to_primitive(diagnostic_for_error(caught.value), policy="redacted-diagnostic")
        == expected
    )
    path = tmp_path / "PRIVATE_FILENAME_829174.xml"
    path.write_bytes(data)
    argv = ["parse", str(path), "--output-policy", "redacted-diagnostic"]
    if json_errors:
        argv.append("--json-errors")
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    if json_errors:
        assert json.loads(output.err) == {
            "error": {"code": expected["code"], "diagnostic": expected}
        }
    else:
        assert output.err == "bankparser: AMBIGUOUS_CAMT_ACCOUNT\n"
