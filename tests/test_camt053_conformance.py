from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bankparser import parse

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install the camt extra to run CAMT.053 conformance tests",
)

FIXTURE = Path("corpus/camt053/basic_valid.camt053.xml")
EXPECTED = Path("corpus/camt053/basic_valid.expected.json")


def test_camt053_fixture_matches_expected_core(canonical_core) -> None:
    expected = json.loads(EXPECTED.read_text())
    result = parse(FIXTURE)
    actual = canonical_core(result)
    assert actual == expected
