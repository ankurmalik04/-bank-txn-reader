from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from bankparser import parse
from bankparser.errors import ParseError

FIXTURE = Path("corpus/mt940/multiple_statements.mt940")


def test_wolph_rejects_multiple_statement_scopes() -> None:
    with pytest.raises(ParseError) as caught:
        parse(FIXTURE, implementation="wolph")
    assert caught.value.code == "MULTIPLE_STATEMENTS"


@pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install the alternative extra to run cross-parser scope tests",
)
def test_bankstatementparser_rejects_multiple_statement_scopes() -> None:
    with pytest.raises(ParseError) as caught:
        parse(FIXTURE, implementation="bankstatementparser")
    assert caught.value.code == "MULTIPLE_STATEMENTS"
