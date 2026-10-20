from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import CsvOptions, InputError, ParseError, parse


@pytest.mark.parametrize(
    "options,amount",
    [
        (CsvOptions(decimal_separator=".", grouping_separator=","), Decimal(1234)),
        (CsvOptions(decimal_separator=","), Decimal("1.234")),
    ],
)
def test_ambiguous_source_requires_an_explicit_interpretation(options, amount):
    result = parse(Path("corpus/csv/ambiguous_amount.csv"), csv_options=options)
    assert result.transactions[0].amount == amount
    assert result.transactions[0].raw["source_fields"]["Amount"] == "1,234"


@pytest.mark.parametrize(
    "text,options,amount",
    [
        ("1.234,56", CsvOptions(",", "."), "1234.56"),
        ("1 234,56", CsvOptions(",", " "), "1234.56"),
        ("1'234.56", CsvOptions(".", "'"), "1234.56"),
        (
            "123456789012345678901234567890.12",
            CsvOptions("."),
            "123456789012345678901234567890.12",
        ),
    ],
)
def test_explicit_separators_preserve_exact_amounts(text, options, amount):
    data = f'Booking Date,Description,Amount,Currency\n2026-10-01,Payment,"{text}",GBP\n'.encode()
    assert parse(data, csv_options=options).transactions[0].amount == Decimal(amount)


@pytest.mark.parametrize(
    "text", ["12,34.56", "1,234,56.00", "1,234.5,6", "NaN", "Infinity", "1e3"]
)
def test_invalid_amounts_do_not_produce_transactions(text):
    data = f'Booking Date,Description,Amount\n2026-10-01,Payment,"{text}"\n'.encode()
    with pytest.raises(ParseError) as caught:
        parse(data, csv_options=CsvOptions(".", ","))
    assert caught.value.code == "INVALID_AMOUNT"
    assert caught.value.location == "CSV line 2, column 'Amount'"


def test_ambiguous_dates_remain_visible_until_a_format_is_supplied():
    data = b"Booking Date,Value Date,Description,Amount\n01/02/2026,02/02/2026,Payment,1.00\n"
    unconfigured = parse(data)
    assert unconfigured.transactions[0].booking_date is None
    warning = next(
        w for w in unconfigured.warnings if w.code == "UNPARSED_TRANSACTION_DATE"
    )
    assert warning.location == "CSV line 2, column 'Booking Date'"
    configured = parse(data, csv_options=CsvOptions(date_format="%d/%m/%Y"))
    assert configured.transactions[0].booking_date.isoformat() == "2026-02-01"
    assert configured.transactions[0].value_date.isoformat() == "2026-02-02"


def test_csv_options_are_rejected_for_other_formats():
    with pytest.raises(InputError, match="only be used with CSV"):
        parse(Path("corpus/mt940/basic_valid.mt940"), csv_options=CsvOptions("."))


def test_explicit_decimal_comma_does_not_accept_a_decimal_point():
    data = b"Booking Date,Description,Amount\n2026-10-01,Payment,1.234\n"
    with pytest.raises(ParseError) as caught:
        parse(data, csv_options=CsvOptions(decimal_separator=","))
    assert caught.value.code == "INVALID_AMOUNT"
