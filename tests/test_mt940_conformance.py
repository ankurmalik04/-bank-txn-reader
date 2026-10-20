from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bankparser import parse

HAS_ALTERNATIVE = importlib.util.find_spec("bankstatementparser") is not None

CORPUS = Path("corpus/mt940")
CASES = (
    "basic_valid",
    "balance_mismatch",
    "missing_description",
    "reversals",
    "missing_opening_balance",
    "missing_closing_balance",
)
IMPLEMENTATIONS = ("wolph", "bankstatementparser")


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("implementation", IMPLEMENTATIONS)
def test_mt940_fixture_matches_expected_core(
    case: str, implementation: str, canonical_core
) -> None:
    if implementation == "bankstatementparser" and not HAS_ALTERNATIVE:
        pytest.skip("optional bankstatementparser implementation is not installed")
    expected = json.loads((CORPUS / f"{case}.expected.json").read_text())
    result = parse(CORPUS / f"{case}.mt940", implementation=implementation)
    assert canonical_core(result) == expected
