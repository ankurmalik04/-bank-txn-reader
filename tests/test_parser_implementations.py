from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from bankparser import parse
from bankparser.serialization import to_primitive

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("bankstatementparser") is None,
    reason="install the optional alternative extra to compare implementations",
)


def _transaction_projection(result):
    transactions = []
    for transaction in result.transactions:
        item = to_primitive(transaction)
        item.pop("raw")
        transactions.append(item)
    return transactions


def test_mt940_implementations_agree_on_basic_fixture() -> None:
    source = Path("corpus/mt940/basic_valid.mt940")

    wolph = parse(source, implementation="wolph")
    alternative = parse(source, implementation="bankstatementparser")

    assert wolph.account.id == alternative.account.id
    assert wolph.account.currency == alternative.account.currency
    assert wolph.statement.id == alternative.statement.id
    assert wolph.statement.sequence == alternative.statement.sequence
    assert wolph.statement.opening_balance == alternative.statement.opening_balance
    assert wolph.statement.closing_balance == alternative.statement.closing_balance
    assert _transaction_projection(wolph) == _transaction_projection(alternative)
    assert wolph.validation.status == "passed"
    assert alternative.validation.status == "passed"
