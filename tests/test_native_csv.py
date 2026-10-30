"""Native CSV safety and the lightweight default installation contract."""

from __future__ import annotations

import csv
import io
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import ParseError, implementations, parse
from bankparser.parsers.csv.bankstatementparser import BankStatementParserCsvAdapter


def test_native_default_works_without_importing_optional_dependencies():
    code = """
import sys
import tempfile
blocked = {"bankstatementparser", "pandas", "numpy", "lxml", "pydantic"}
class BlockOptional:
    def find_spec(self, fullname, path=None, target=None):
        assert fullname.split(".")[0] not in blocked, fullname
        return None
sys.meta_path.insert(0, BlockOptional())
def no_temp_files(*args, **kwargs):
    raise AssertionError("native CSV must not write temporary files")
tempfile.TemporaryDirectory = no_temp_files
from bankparser import parse
result = parse(b"Booking Date,Amount,Currency\\n2026-10-01,1.25,GBP\\n")
assert result.source.implementation == "native"
assert result.source.implementation_version == result.source.bankparser_version
assert str(result.transactions[0].amount) == "1.25"
parse("corpus/mt940/basic_valid.mt940")
assert not blocked.intersection(sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True)
    assert implementations("csv") == ("bankstatementparser", "native")


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_native_preserves_multiline_cells_bom_blank_lines_and_dates(delimiter, newline):
    source = io.StringIO(newline="")
    source.write(newline)
    writer = csv.writer(source, delimiter=delimiter, lineterminator=newline)
    writer.writerow(["Booking Date", "Value Date", "Amount", "Currency", "Description"])
    writer.writerow(
        ["2026-10-03", "2026-10-02", "-10.00", "GBP", f"Café{newline}invoice"]
    )
    writer.writerow(["2026-10-01", "2026-10-04", "2.00", "GBP", "Refund"])
    result = parse(source.getvalue().encode("utf-8-sig"))
    assert result.source.implementation == "native"
    assert [t.amount for t in result.transactions] == [
        Decimal("-10.00"),
        Decimal("2.00"),
    ]
    assert result.transactions[0].description == f"Café{newline}invoice"
    assert (
        result.transactions[0].raw["source_fields"]["Description"]
        == f"Café{newline}invoice"
    )
    assert [t.raw["source_line"] for t in result.transactions] == [4, 5]
    assert result.statement.start_date == date(2026, 10, 1)
    assert result.statement.end_date == date(2026, 10, 4)


@pytest.mark.parametrize(
    "data,code",
    [
        (b"Booking Date,Amount\n\n", "EMPTY_STATEMENT"),
        (b"Booking Date,Amount,Debit\n2026-10-01,1.00,1.00\n", "AMBIGUOUS_COLUMNS"),
        (b"Booking Date,Debit,Credit\n2026-10-01,,\n", "MISSING_AMOUNT"),
        (b"Booking Date,Debit,Credit\n2026-10-01,1.00,2.00\n", "AMBIGUOUS_MOVEMENT"),
        (
            b"Booking Date,Amount,Account\n2026-10-01,1.00,A\n2026-10-02,2.00,B\n",
            "MULTIPLE_STATEMENTS",
        ),
        (
            b"Booking Date,Amount,Currency\n2026-10-01,1.00,GBP\n2026-10-02,2.00,EUR\n",
            "MULTIPLE_STATEMENTS",
        ),
        (
            b'Booking Date,Amount,Description\n2026-10-01,1.00,"unterminated\n',
            "INVALID_CSV",
        ),
        (
            b'Booking Date,Amount,Description\n2026-10-01,1.00,"'
            + b"x" * 10000
            + b'\xff"\n',
            "INVALID_CSV",
        ),
    ],
)
def test_native_rejects_invalid_rows_and_scopes(data, code):
    with pytest.raises(ParseError) as caught:
        parse(data)
    assert caught.value.code == code


def test_repeated_warnings_keep_first_location():
    data = b"Booking Date,Amount\n02/03/2026,1.00\n03/04/2026,2.00\n"
    result = parse(data)
    warnings = [w for w in result.warnings if w.code == "UNPARSED_TRANSACTION_DATE"]
    assert len(warnings) == 1
    assert warnings[0].location == "CSV line 2, column 'Booking Date'"


def test_native_and_optional_backend_preserve_split_amounts_with_zero_cells(
    monkeypatch,
):
    import importlib.util

    if importlib.util.find_spec("bankstatementparser") is None:
        pytest.skip("install the alternative extra for explicit backend selection")
    from bankstatementparser.additional_parsers import CsvStatementParser

    original_init = CsvStatementParser.__init__
    normalized = []

    def check_normalized_cells(parser, path):
        # Both monetary columns are supplied; the inactive zero must stay zero.
        with Path(path).open(newline="") as source:
            normalized.extend(csv.DictReader(source))
        original_init(parser, path)

    monkeypatch.setattr(CsvStatementParser, "__init__", check_normalized_cells)
    data = b"Booking Date,Description,Debit,Credit,Currency\n2026-10-01,Payment,1.25,0.00,GBP\n2026-10-02,Refund,0.00,2.50,GBP\n"
    native = parse(data)
    backend = parse(data, implementation="bankstatementparser")
    assert native.transactions == backend.transactions
    assert [t.amount for t in backend.transactions] == [
        Decimal("-1.25"),
        Decimal("2.50"),
    ]
    assert [(row["Debit"], row["Credit"]) for row in normalized] == [
        ("1.25", "0"),
        ("0", "2.50"),
    ]


@pytest.mark.parametrize("failure", ["count", "exception"])
def test_optional_csv_backend_keeps_failure_checks(monkeypatch, failure):
    from types import SimpleNamespace

    adapter = object.__new__(BankStatementParserCsvAdapter)

    class Backend:
        def __init__(self, path):
            pass

        def parse(self):
            if failure == "exception":
                raise ValueError("backend failed")
            return SimpleNamespace(to_dict=lambda orient: [])

    adapter._parser_class = Backend
    from bankparser.parsers.base import ParseContext

    with pytest.raises(ParseError) as caught:
        adapter.parse(b"Booking Date,Amount\n2026-10-01,1.00\n", ParseContext())
    assert caught.value.code == (
        "TRANSACTION_COUNT_MISMATCH" if failure == "count" else "PARSE_ERROR"
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "headers,values,options,code,column",
    [
        (
            ["Booking Date", "Value Date", "Amount", "Currency"],
            ["invalid-date", "2026-10-01", "1.00", "GBP"],
            None,
            "UNPARSED_TRANSACTION_DATE",
            "column 'Booking Date'",
        ),
        (
            ["Date", "Amount", "Currency"],
            ["2026-10-01", "1.00", "GBP"],
            None,
            "AMBIGUOUS_DATE_SEMANTICS",
            "column 'Date'",
        ),
        (
            ["Booking Date", "Amount", "Currency", "Balance"],
            ["2026-10-01", "1.00", "GBP", "10.00"],
            None,
            "CSV_BALANCE_ORDER_UNKNOWN",
            "column 'Balance'",
        ),
        (
            ["Booking Date", "Amount", "Currency"],
            ["2026-10-01", "1.00", ""],
            {"default_currency": "GBP"},
            "CONFIGURED_CURRENCY",
            "currency",
        ),
    ],
)
def test_multiline_record_warnings_use_start_line_and_preserve_raw_end(
    newline, headers, values, options, code, column
):
    from bankparser import CsvOptions, diagnostics_for

    source = io.StringIO(newline="")
    writer = csv.writer(source, lineterminator=newline)
    writer.writerow([*headers, "Description"])
    writer.writerow([*values, f"First line{newline}Second line"])
    # Repeated warnings still retain the first record's starting location.
    writer.writerow([*values, f"Third line{newline}Fourth line"])
    result = parse(
        source.getvalue().encode(),
        csv_options=CsvOptions(**options) if options else None,
    )
    warnings = [w for w in result.warnings if w.code == code]
    assert len(warnings) == 1
    assert warnings[0].location == f"CSV line 2, {column}"
    assert [t.raw["source_line_start"] for t in result.transactions] == [2, 4]
    assert [t.raw["source_line"] for t in result.transactions] == [3, 5]
    assert [t.amount for t in result.transactions] == [Decimal("1.00")] * 2
    assert result.transactions[0].description == f"First line{newline}Second line"
    diagnostics = {d.code: d for d in diagnostics_for(result)}
    assert diagnostics[code].source_locations == (f"CSV line 2, {column}",)
    if code == "UNPARSED_TRANSACTION_DATE":
        assert diagnostics["TRANSACTION_BOOKING_DATES"].source_locations == (
            "CSV line 2",
            "CSV line 4",
        )


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "headers,values,options,code,suffix",
    [
        (["Amount"], ["not-money"], None, "INVALID_AMOUNT", ", column 'Amount'"),
        (["Amount"], ["1.234"], None, "AMBIGUOUS_AMOUNT", ", column 'Amount'"),
        (
            ["Debit", "Credit"],
            ["not-money", ""],
            None,
            "INVALID_AMOUNT",
            ", column 'Debit'",
        ),
        (
            ["Debit", "Credit"],
            ["", "not-money"],
            None,
            "INVALID_AMOUNT",
            ", column 'Credit'",
        ),
        (
            ["Debit", "Credit"],
            ["-1", ""],
            None,
            "SIGNED_DEBIT_CREDIT",
            ", column 'Debit'",
        ),
        (["Debit", "Credit"], ["", ""], None, "MISSING_AMOUNT", ""),
        (["Debit", "Credit"], ["1", "2"], None, "AMBIGUOUS_MOVEMENT", ""),
        (
            ["Amount"],
            ["1"],
            {"expected_currency": "EUR"},
            "CSV_CURRENCY_CONSTRAINT",
            ", currency",
        ),
        (["Amount"], ["1", "extra-cell"], None, "INVALID_CSV_ROW", ""),
    ],
)
def test_multiline_record_errors_use_start_line_after_prior_multiline_record(
    newline, headers, values, options, code, suffix
):
    from bankparser import CsvOptions

    source = io.StringIO(newline="")
    writer = csv.writer(source, lineterminator=newline)
    writer.writerow(["Booking Date", "Currency", "Description", *headers])
    # Blank rows and a preceding multiline record count toward physical lines.
    source.write(newline)
    good = ["1"] if headers == ["Amount"] else ["1", ""]
    currency = "EUR" if options else "GBP"
    writer.writerow(["2026-10-01", currency, f"Earlier{newline}record", *good])
    writer.writerow(["2026-10-02", "GBP", f"First line{newline}Second line", *values])
    with pytest.raises(ParseError) as caught:
        parse(
            source.getvalue().encode(),
            csv_options=CsvOptions(**options) if options else None,
        )
    assert caught.value.code == code
    assert caught.value.location == f"CSV line 5{suffix}"
