"""Real-backend regression tests for previously reproduced data-loss cases."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bankparser import ParseError, parse

CASES = [
    pytest.param(case, implementation, id=f"{Path(case['file']).stem}-{implementation}")
    for case in json.loads(Path("corpus/regressions.json").read_text())
    for implementation in case["implementations"]
]


@pytest.mark.parametrize("case,implementation", CASES)
def test_regression_corpus(case, implementation, canonical_core):
    if (
        implementation == "bankstatementparser"
        and importlib.util.find_spec("bankstatementparser") is None
    ):
        pytest.skip("install bankparser-runtime[all] for the complete corpus")
    if implementation == "ofxparse" and importlib.util.find_spec("ofxparse") is None:
        pytest.skip("install bankparser-runtime[ofx] for OFX regressions")
    expected = json.loads(Path(case["expected"]).read_text())
    if "error" in expected:
        with pytest.raises(ParseError) as caught:
            parse(Path(case["file"]), implementation=implementation)
        assert caught.value.code == expected["error"]["code"]
    else:
        assert (
            canonical_core(parse(Path(case["file"]), implementation=implementation))
            == expected
        )


def test_csv_unmapped_cells_are_preserved():
    transaction = parse(Path("corpus/csv/all_fields.csv")).transactions[0]
    assert transaction.raw["source_fields"]["Customer Code"] == "SYNTH-CUSTOM-1"
    assert transaction.raw["source_line"] == 2


def test_alternative_mt940_rejects_contradictory_currencies():
    pytest.importorskip("bankstatementparser")
    with pytest.raises(ParseError, match="Conflicting MT940 statement currencies"):
        parse(
            Path("corpus/mt940/currency_conflict.mt940"),
            implementation="bankstatementparser",
        )


def test_camt_keeps_multiple_narratives_and_payment_references():
    pytest.importorskip("bankstatementparser")
    transaction = parse(Path("corpus/camt053/all_fields.camt053.xml")).transactions[0]
    assert transaction.raw["structured_references"] == ("SYNTH-RF-7",)
    assert transaction.raw["payment_references"] == {
        "InstrId": "SYNTH-INSTR-1",
        "AcctSvcrRef": "SYNTH-BANK-1",
        "EndToEndId": "SYNTH-E2E-1",
    }
    assert transaction.raw["source_path"] == "Stmt/Ntry[1]/NtryDtls/TxDtls[1]"
