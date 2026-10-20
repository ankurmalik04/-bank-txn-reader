"""Interpret the same ambiguous source amount using two explicit conventions."""

from pathlib import Path

from bankparser import CsvOptions, ParseError, parse

source = Path(__file__).resolve().parents[1] / "corpus/csv/ambiguous_amount.csv"
try:
    parse(source)
except ParseError as exc:
    print(f"Unconfigured: {exc.code} at {exc.location}")

for label, options in (
    ("Grouped integer", CsvOptions(decimal_separator=".", grouping_separator=",")),
    ("Decimal comma", CsvOptions(decimal_separator=",")),
):
    result = parse(source, csv_options=options)
    print(f"{label}: {result.transactions[0].amount}")
