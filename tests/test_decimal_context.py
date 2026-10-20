"""Parsing must preserve source amounts regardless of the embedding application's context."""

import importlib.util
import json
from decimal import Inexact, localcontext
from pathlib import Path

import pytest

from bankparser import parse


@pytest.mark.parametrize(
    "family,name,implementation",
    [
        ("mt940", "basic_valid.mt940", "wolph"),
        ("mt940", "basic_valid.mt940", "bankstatementparser"),
        ("csv", "basic_valid.csv", "native"),
        ("camt053", "basic_valid.camt053.xml", "bankstatementparser"),
        ("ofx", "basic_valid.ofx", "bankstatementparser"),
    ],
)
def test_public_parse_is_independent_of_decimal_context(
    family, name, implementation, canonical_core
):
    if (
        implementation == "bankstatementparser"
        and importlib.util.find_spec("bankstatementparser") is None
    ):
        pytest.skip("install all for optional adapters")
    expected = json.loads(
        Path(f"corpus/{family}/basic_valid.expected.json").read_text()
    )
    with localcontext() as context:
        context.prec = 3
        context.Emax = 3
        context.traps[Inexact] = True
        before = context.copy()
        result = parse(Path(f"corpus/{family}/{name}"), implementation=implementation)
        assert canonical_core(result) == expected
        assert context.prec == before.prec
        assert context.Emax == before.Emax
        assert context.traps == before.traps
        assert context.flags == before.flags


@pytest.mark.parametrize("implementation", ["wolph", "bankstatementparser"])
def test_mt940_bom_is_detected_before_adapter_selection(implementation, canonical_core):
    if (
        implementation == "bankstatementparser"
        and importlib.util.find_spec("bankstatementparser") is None
    ):
        pytest.skip("install alternative for the backend adapter")
    source = b"\xef\xbb\xbf" + Path("corpus/mt940/basic_valid.mt940").read_bytes()
    expected = json.loads(Path("corpus/mt940/basic_valid.expected.json").read_text())
    assert canonical_core(parse(source, implementation=implementation)) == expected
