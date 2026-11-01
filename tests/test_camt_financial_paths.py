"""Do not silently discard CAMT financial nodes outside supported paths."""

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


def document():
    root = E.fromstring(Path("corpus/camt053/basic_valid.camt053.xml").read_bytes())
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    return root


@pytest.mark.parametrize("tag", ["Ntry", "Bal", "TxDtls"])
@pytest.mark.parametrize("move", [False, True])
def test_misplaced_financial_node_is_rejected(tag, move):
    root = document()
    statement = root.find(".//Stmt")
    node = statement.find(".//" + tag)
    extension = E.SubElement(statement, "Extension")
    extension.append(deepcopy(node))
    if move:
        parent = next(p for p in statement.iter() if node in list(p))
        parent.remove(node)
    with pytest.raises(ParseError) as caught:
        _validate_source(statement)
    assert caught.value.code == "INVALID_CAMT_FINANCIAL_STRUCTURE"
    assert caught.value.location == "Stmt/Extension[1]/" + tag + "[1]"


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None, reason="camt extra"
)
@pytest.mark.parametrize(
    "parent_path", [".", "./BkToCstmrStmt", "./BkToCstmrStmt/GrpHdr"]
)
def test_activity_outside_statement_is_rejected_by_public_api(parent_path):
    root = document()
    E.SubElement(root.find(parent_path), "Extension").append(
        deepcopy(root.find(".//Ntry"))
    )
    root.set("xmlns", "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    with pytest.raises(ParseError) as caught:
        parse(E.tostring(root))
    assert caught.value.code == "INVALID_CAMT_FINANCIAL_STRUCTURE"
    assert caught.value.format == "camt053"
    assert caught.value.location.endswith("/Extension[1]/Ntry[1]")


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None, reason="camt extra"
)
def test_foreign_extension_financial_names_are_not_camt_activity():
    root = document()
    extension = E.SubElement(root.find(".//Stmt"), "{urn:example:metadata}Extension")
    for tag in ("Ntry", "Bal", "TxDtls"):
        E.SubElement(extension, "{urn:example:metadata}" + tag).text = "metadata"
    root.set("xmlns", "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    result = parse(E.tostring(root))
    assert len(result.transactions) == 2
    assert result.validation.status == "passed"


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None, reason="camt extra"
)
@pytest.mark.parametrize("json_errors", [False, True])
def test_financial_path_code_survives_redaction(tmp_path, capsys, json_errors):
    root = document()
    statement = root.find(".//Stmt")
    extension = E.SubElement(statement, "PRIVATE_EXTENSION_829174")
    extension.append(deepcopy(statement.find("Ntry")))
    root.set("xmlns", "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02")
    data = E.tostring(root)
    with pytest.raises(ParseError) as caught:
        parse(data)
    expected = {
        "diagnostic_schema_version": "1",
        "code": "INVALID_CAMT_FINANCIAL_STRUCTURE",
        "severity": "error",
        "format": "camt053",
        "canonical_field": None,
    }
    assert to_primitive(
        diagnostic_for_error(caught.value), policy="redacted-diagnostic"
    ) == expected
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
        assert output.err == "bankparser: INVALID_CAMT_FINANCIAL_STRUCTURE\n"
