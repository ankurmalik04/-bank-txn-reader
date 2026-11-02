"""Currency syntax must be checked before Unicode case conversion."""

import importlib
from types import SimpleNamespace

import pytest

from bankparser.errors import ParseError


@pytest.mark.parametrize("format", ["ofx", "mt940"])
@pytest.mark.parametrize("value", ["ßP", "ＵＳＤ", "USDD", "12A", "GB"])
def test_optional_adapters_reject_invalid_currency(format, value):
    module = importlib.import_module(f"bankparser.parsers.{format}.bankstatementparser")
    with pytest.raises(ParseError) as caught:
        module._currency(value)
    assert caught.value.code == "INVALID_CURRENCY"
    assert caught.value.location


@pytest.mark.parametrize("format", ["ofx", "mt940"])
@pytest.mark.parametrize("value", [None, "", "  ", float("nan")])
def test_optional_adapters_preserve_missing_currency(format, value):
    module = importlib.import_module(f"bankparser.parsers.{format}.bankstatementparser")
    assert module._currency(value) is None
    assert module._currency(" gbp ") == "GBP"


def test_wolph_balance_currency_rejects_unicode():
    from bankparser.parsers.mt940.wolph import _balance_currency

    with pytest.raises(ParseError) as caught:
        _balance_currency(SimpleNamespace(amount=SimpleNamespace(currency="ßP")))
    assert caught.value.code == "INVALID_CURRENCY"
