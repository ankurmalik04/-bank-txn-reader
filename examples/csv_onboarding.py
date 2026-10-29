"""Runnable synthetic CSV onboarding example using the 0.5.0a2 API."""

from datetime import date
from decimal import Decimal

from bankparser import CsvOptions, parse


def main() -> None:
    # Independently invented source and expected values, not a bank export.
    source = (
        b"Booking Date;Value Date;Amount;Currency;Description;Reference\n"
        b'04/05/2026;05/05/2026;-1.234,50;EUR;"Parts; invoice";SYNTH-1\n'
        b"06/05/2026;06/05/2026;12,50;EUR;Refund;SYNTH-2\n"
    )
    result = parse(
        source,
        csv_options=CsvOptions(
            decimal_separator=",", grouping_separator=".", date_format="%d/%m/%Y"
        ),
    )
    assert [tx.amount for tx in result.transactions] == [
        Decimal("-1234.50"),
        Decimal("12.50"),
    ]
    assert result.transactions[0].booking_date == date(2026, 5, 4)
    assert result.transactions[0].value_date == date(2026, 5, 5)
    assert result.transactions[0].description == "Parts; invoice"
    assert [tx.reference for tx in result.transactions] == ["SYNTH-1", "SYNTH-2"]
    assert result.validation.status == "warning"
    print(f"format={result.source.format} transactions={len(result.transactions)}")
    print(f"validation={result.validation.status}")
    for check in result.validation.checks:
        if check.status != "passed":
            print(f"check={check.code} status={check.status}")


if __name__ == "__main__":
    main()
