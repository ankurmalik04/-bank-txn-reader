"""Adversarial source inputs must fail before yielding misleading financial data."""

from datetime import date
from pathlib import Path

import pytest

from bankparser import CsvOptions, InputError, ParseError, parse
from bankparser.parsers.mt940.source import source_fields
from bankparser.parsers.ofx.bankstatementparser import _decode_ofx


@pytest.mark.parametrize(
    "data,code",
    [
        (b":25:\xff\n", "INVALID_ENCODING"),
        (b":61:not-a-transaction\n", "UNSUPPORTED_TRANSACTION"),
        (b":61:261332D10,00NTRFREF\n", "INVALID_DATE"),
        (b":61:2610020230D10,00NTRFREF\n", "INVALID_DATE"),
        (b":60F:C261001GBP0,00\n:60M:C261001GBP0,00\n", "MULTIPLE_STATEMENTS"),
        (b":62F:C261001GBP0,00\n:62M:C261001GBP0,00\n", "MULTIPLE_STATEMENTS"),
    ],
)
def test_mt940_rejects_unrepresentable_source_fields(data, code):
    with pytest.raises(ParseError) as caught:
        source_fields(data)
    assert caught.value.code == code


def test_mt940_entry_dates_cross_year_without_inventing_missing_dates():
    _, transactions = source_fields(
        b":61:2612310101C10,00NTRFREF//BANK\n"
        b":61:2701011231D10,00NTRFREF\n"
        b":61:270101D10,00NTRFREF\n"
    )
    assert [tx["booking_date"] for tx in transactions] == [
        date(2027, 1, 1),
        date(2026, 12, 31),
        None,
    ]
    assert transactions[0]["bank_reference"] == "BANK"
    assert [tx["source_line"] for tx in transactions] == [1, 2, 3]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"decimal_separator": ";"},
        {"grouping_separator": "_"},
        {"grouping_separator": ","},
        {"decimal_separator": ",", "grouping_separator": ","},
    ],
)
def test_invalid_csv_configuration_is_rejected(kwargs):
    with pytest.raises(InputError):
        CsvOptions(**kwargs)


@pytest.mark.parametrize(
    "data",
    [
        b"CHARSET:932\n<OFX></OFX>",
        b"CHARSET:missing-codec\n<OFX></OFX>",
        b"ENCODING:USASCII\n<OFX>\xff</OFX>",
    ],
)
def test_ofx_rejects_unsupported_or_invalid_encodings(data):
    with pytest.raises(ParseError) as caught:
        _decode_ofx(data)
    assert caught.value.code == "INVALID_ENCODING"


def test_ofx_honors_xml_encoding_and_ascii_headers():
    assert "café" in _decode_ofx(
        '<?xml version="1.0" encoding="iso-8859-1"?><OFX>café</OFX>'.encode("latin-1")
    )
    assert _decode_ofx(b"ENCODING:USASCII\n<OFX></OFX>").endswith("<OFX></OFX>")


def test_csv_invalid_configured_date_stays_missing():
    result = parse(
        b"Booking Date,Description,Amount\n31/02/2026,Payment,1.00\n",
        csv_options=CsvOptions(date_format="%d/%m/%Y"),
    )
    assert result.transactions[0].booking_date is None
    assert "UNPARSED_TRANSACTION_DATE" in {w.code for w in result.warnings}


def test_mt940_transaction_count_mismatch_is_rejected(monkeypatch):
    import mt940

    native = mt940.parse_statements(
        Path("corpus/mt940/basic_valid.mt940").read_bytes()
    )[0]
    native.transactions.pop()
    monkeypatch.setattr(mt940, "parse_statements", lambda *args, **kwargs: [native])
    with pytest.raises(ParseError) as caught:
        parse(Path("corpus/mt940/basic_valid.mt940"))
    assert caught.value.code == "TRANSACTION_COUNT_MISMATCH"
