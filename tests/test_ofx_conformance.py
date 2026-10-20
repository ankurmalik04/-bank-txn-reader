from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bankparser import parse

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ofxparse") is None,
    reason="install the ofx extra to run OFX/QFX conformance tests",
)

FIXTURE = Path("corpus/ofx/basic_valid.ofx")
EXPECTED = Path("corpus/ofx/basic_valid.expected.json")


def test_ofx_fixture_matches_expected_core(canonical_core) -> None:
    expected = json.loads(EXPECTED.read_text())
    result = parse(FIXTURE)
    actual = canonical_core(result)
    assert actual == expected


def test_qfx_uses_the_same_ofx_format_family() -> None:
    result = parse(Path("corpus/ofx/basic_valid.qfx"))
    assert result.source.format == "ofx"
    assert result.source.file_name == "basic_valid.qfx"
    assert result.account.id == "SYNTH-QFX-CARD-1"
    assert result.account.currency == "USD"
    assert len(result.transactions) == 1
    assert result.transactions[0].amount == -7
    assert result.transactions[0].transaction_id == "SYNTH-QFX-1"
    assert result.statement.closing_balance == -7
