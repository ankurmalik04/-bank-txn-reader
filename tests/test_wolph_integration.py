from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("mt940")

from bankparser.parsers.base import ParseContext
from bankparser.parsers.mt940.wolph import WolphMt940Adapter


def test_real_wolph_parser_against_synthetic_fixture() -> None:
    fixture = Path("corpus/mt940/basic_valid.mt940")
    adapter = WolphMt940Adapter()
    result = adapter.parse(fixture.read_bytes(), ParseContext(fixture.name))

    assert result.account.id == "GB75TEST00000000000001"
    assert result.account.currency == "GBP"
    assert result.statement.id == "1"
    assert result.statement.sequence == "1"
    assert result.statement.opening_balance == Decimal("500.00")
    assert result.statement.closing_balance == Decimal("561.25")
    assert [tx.amount for tx in result.transactions] == [
        Decimal("-18.75"),
        Decimal("80.00"),
    ]
