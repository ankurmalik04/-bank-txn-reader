"""Bounded deterministic properties; case parameters are complete reproducers."""

import csv
import io
from dataclasses import replace
from datetime import date
from decimal import Decimal, Inexact, Rounded, localcontext

import pytest

from bankparser import diagnostics_for, parse
from bankparser.comparison import compare_results
from bankparser.models import Statement
from bankparser.serialization import to_primitive
from bankparser.validation import validate


def decimal_units(units, scale, *, negative_zero=False):
    """Construct an exact oracle without Decimal arithmetic or source parsing."""
    digits = tuple(int(c) for c in str(abs(units)))
    return Decimal((int(units < 0 or negative_zero), digits, -scale))


def literal(units, scale, *, negative_zero=False):
    digits = str(abs(units)).zfill(scale + 1)
    number = digits if scale == 0 else digits[:-scale] + "." + digits[-scale:]
    return ("-" if units < 0 or negative_zero else "") + number


@pytest.mark.parametrize("scale", [0, 2, 18, 120])
@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_exact_count_order_scale_and_conservation_under_hostile_context(
    scale, delimiter
):
    # Cancellation plus a one-unit remainder exercises very different magnitudes.
    units = [10**125 + 17, -(10**125), -17, 1, 0, 0]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(["Booking Date", "Amount", "Currency", "Description", "Reference"])
    descriptions = [f'row {i} {delimiter} "quoted"\ncontinuation' for i in range(6)]
    for index, amount in enumerate(units):
        writer.writerow(
            [
                "2026-10-01",
                literal(amount, scale, negative_zero=index == 5),
                "GBP",
                descriptions[index],
                "REPEATED-REFERENCE",
            ]
        )

    with localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        before = context.copy()
        result = parse(stream.getvalue().encode("utf-8-sig"))
        expected = [
            decimal_units(n, scale, negative_zero=i == 5) for i, n in enumerate(units)
        ]
        assert [tx.amount.as_tuple() for tx in result.transactions] == [
            n.as_tuple() for n in expected
        ]
        assert [tx.description for tx in result.transactions] == descriptions
        assert [tx.reference for tx in result.transactions] == [
            "REPEATED-REFERENCE"
        ] * 6
        # Python integer summation is the independent booked-sum oracle.
        statement = Statement(
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 1),
            opening_balance=decimal_units(0, scale),
            closing_balance=decimal_units(sum(units), scale),
            opening_balance_currency="GBP",
            closing_balance_currency="GBP",
        )
        checks = validate(result.account, statement, result.transactions).checks
        assert (
            next(c for c in checks if c.code == "BALANCE_RECONCILIATION").status
            == "passed"
        )
        wrong = replace(statement, closing_balance=decimal_units(sum(units) + 1, scale))
        checks = validate(result.account, wrong, result.transactions).checks
        assert (
            next(c for c in checks if c.code == "BALANCE_RECONCILIATION").status
            == "failed"
        )
        assert context.flags == before.flags
        assert context.traps == before.traps
        assert (context.prec, context.Emax, context.Emin) == (2, 2, -2)


@pytest.mark.parametrize("missing", [(0,), (2, 10), (0, 1, 11)])
def test_generated_diagnostics_track_physical_lines_after_multiline_records(missing):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["Booking Date", "Value Date", "Amount", "Currency", "Description"])
    locations = []
    line = 2
    for index in range(12):
        locations.append(f"CSV line {line}")
        description = (
            f"PRIVATE_MARKER_{index}\nextra" if index % 2 else f"PRIVATE_MARKER_{index}"
        )
        writer.writerow(
            [
                "" if index in missing else "2026-10-01",
                "2026-10-01",
                "1.00",
                "",
                description,
            ]
        )
        line += 2 if index % 2 else 1
    result = parse(stream.getvalue().encode())
    diagnostics = {item.code: item for item in diagnostics_for(result)}
    booking = diagnostics["TRANSACTION_BOOKING_DATES"]
    assert booking.record_indices == missing
    assert booking.source_locations == tuple(locations[i] for i in missing)
    currency = diagnostics["TRANSACTION_CURRENCIES"]
    assert currency.record_indices == tuple(range(12))
    assert currency.source_locations == tuple(locations)
    full = to_primitive(result)
    redacted = to_primitive(tuple(diagnostics.values()), policy="redacted-diagnostic")
    assert "PRIVATE_MARKER" not in repr(redacted)
    assert all(
        "source_locations" not in item and "record_indices" not in item
        for item in redacted
    )
    assert to_primitive(result) == full


@pytest.mark.parametrize("index", [0, 2, 10, 11])
@pytest.mark.parametrize("reference", [None, "", "<missing>", "PRIVATE_REFERENCE"])
def test_single_generated_mutation_has_one_comparison_coordinate(index, reference):
    source = (
        "Booking Date,Amount,Currency,Reference\n"
        + "2026-10-01,1.00,GBP,ORIGINAL\n" * 12
    )
    original = parse(source.encode())
    transactions = list(original.transactions)
    transactions[index] = replace(transactions[index], reference=reference)
    changed = replace(original, transactions=tuple(transactions))
    report = compare_results({"native": original, "other": changed})
    assert len(report.differences) == 1
    difference = report.differences[0]
    assert difference.path == f"transactions[{index}].reference"
    assert difference.values == {"native": "ORIGINAL", "other": reference}
    assert difference.present == {"native": True, "other": True}
    redacted = to_primitive(report, policy="redacted-diagnostic")
    assert redacted["difference_count"] == 1
    assert "PRIVATE_REFERENCE" not in repr(redacted)
