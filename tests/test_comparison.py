from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, Inexact, localcontext

import pytest

from bankparser.comparison import compare_results
from bankparser.errors import ComparisonError
from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationCheck,
    ValidationResult,
)


def _result(
    implementation: str, booking_date: date | None, raw: dict[str, str]
) -> ParseResult:
    return ParseResult(
        schema_version="1.0",
        source=SourceMetadata(
            format="mt940",
            implementation=implementation,
            implementation_version="1",
            bankparser_version="0.1.0",
        ),
        account=Account(id="A", currency="GBP"),
        statement=Statement(id="1"),
        transactions=(
            Transaction(
                booking_date=booking_date,
                value_date=date(2026, 10, 2),
                amount=Decimal("10.00"),
                currency="GBP",
                raw=raw,
            ),
        ),
        validation=ValidationResult(status="passed"),
    )


def test_comparison_ignores_source_and_raw_but_reports_canonical_difference() -> None:
    report = compare_results(
        {
            "one": _result("one", date(2026, 10, 2), {"native": "one"}),
            "two": _result("two", None, {"native": "two"}),
        }
    )

    assert not report.matches
    assert [difference.path for difference in report.differences] == [
        "transactions[0].booking_date"
    ]


def test_comparison_requires_two_results() -> None:
    with pytest.raises(ComparisonError):
        compare_results({"one": _result("one", None, {})})


def test_comparison_uses_one_snapshot_when_source_file_changes(tmp_path, monkeypatch):
    from bankparser import api, compare
    from bankparser.parsers.base import CanonicalData
    from bankparser.parsers.registry import ParserRegistry

    source = tmp_path / "changing.csv"
    original = b"Booking Date,Amount,Currency\n2026-10-01,1.00,GBP\n"
    source.write_bytes(original)
    seen = []

    class Adapter:
        format = "csv"
        implementation_version = "1"

        def __init__(self, implementation):
            self.id = implementation

        def parse(self, data, context):
            seen.append(data)
            source.write_bytes(b"different content")
            return CanonicalData(Account(currency="GBP"), Statement(), ())

    registry = ParserRegistry()
    registry.register(
        format="csv", implementation="one", factory=lambda: Adapter("one"), default=True
    )
    registry.register(
        format="csv", implementation="two", factory=lambda: Adapter("two")
    )
    monkeypatch.setattr(api, "_default_registry", lambda: registry)
    assert compare(source).matches
    assert seen == [original, original]


def _money_result(amount, *, reference=None):
    result = _result("test", None, {})
    return replace(
        result,
        statement=Statement(
            opening_balance=Decimal(amount), closing_balance=Decimal(amount)
        ),
        transactions=(
            replace(
                result.transactions[0], amount=Decimal(amount), reference=reference
            ),
        ),
        validation=ValidationResult(
            "passed",
            (
                ValidationCheck(
                    "BALANCE_RECONCILIATION",
                    "passed",
                    "same",
                    expected=amount,
                    actual=amount,
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    "one,two",
    [
        ("10.00", "10.000"),
        ("-0.00", "0"),
        ("123456789012345678901234567890.00", "123456789012345678901234567890"),
    ],
)
def test_comparison_uses_exact_monetary_values_without_rounding(one, two):
    with localcontext() as context:
        context.prec = 2
        context.Emax = 9
        context.traps[Inexact] = True
        before = context.copy()
        assert compare_results(
            {"one": _money_result(one), "two": _money_result(two)}
        ).matches
        assert context.flags == before.flags
        assert context.prec == before.prec
        assert context.Emax == before.Emax
        assert context.traps == before.traps


def test_numeric_comparison_retains_original_values_for_real_differences():
    report = compare_results(
        {"one": _money_result("10.00"), "two": _money_result("10.001")}
    )
    assert not report.matches
    assert len(report.differences) == 5
    assert all(
        d.values == {"one": "10.00", "two": "10.001"} for d in report.differences
    )


def test_numeric_looking_references_and_nonmonetary_checks_still_compare_exactly():
    one, two = (
        _money_result("10.00", reference="10.00"),
        _money_result("10.000", reference="10.000"),
    )
    one = replace(
        one,
        validation=ValidationResult(
            "passed", (ValidationCheck("OTHER", "passed", "same", expected="10.00"),)
        ),
    )
    two = replace(
        two,
        validation=ValidationResult(
            "passed", (ValidationCheck("OTHER", "passed", "same", expected="10.000"),)
        ),
    )
    report = compare_results({"one": one, "two": two})
    assert [d.path for d in report.differences] == [
        "transactions[0].reference",
        "validation.checks[0].expected",
    ]


def test_missing_balance_is_not_equal_to_zero():
    one = _money_result("0")
    two = replace(one, statement=replace(one.statement, opening_balance=None))
    assert [d.path for d in compare_results({"one": one, "two": two}).differences] == [
        "statement.opening_balance"
    ]


@pytest.mark.parametrize(
    "one,two", [("not a number", "different text"), ("NaN", "Infinity")]
)
def test_custom_balance_check_text_stays_exact_without_context_side_effects(one, two):
    first, second = _money_result("10"), _money_result("10")
    first = replace(
        first,
        validation=ValidationResult(
            "failed", (replace(first.validation.checks[0], expected=one),)
        ),
    )
    second = replace(
        second,
        validation=ValidationResult(
            "failed", (replace(second.validation.checks[0], expected=two),)
        ),
    )
    with localcontext() as context:
        before = context.copy()
        report = compare_results({"one": first, "two": second})
        assert context.flags == before.flags
    assert [d.path for d in report.differences] == ["validation.checks[0].expected"]


def test_comparison_rejects_csv_options_for_non_csv_input():
    from bankparser import CsvOptions, InputError, compare

    with pytest.raises(InputError, match="CSV input"):
        compare(
            "corpus/mt940/basic_valid.mt940",
            implementations=("wolph", "bankstatementparser"),
            csv_options=CsvOptions("."),
        )


def test_explicit_comparison_never_runs_an_unselected_default(monkeypatch):
    from bankparser import api, compare
    from bankparser.parsers.base import CanonicalData
    from bankparser.parsers.registry import ParserRegistry

    seen = []

    class Adapter:
        format = "csv"
        implementation_version = "1"

        def __init__(self, identity):
            self.id = identity

        def parse(self, data, context):
            seen.append(self.id)
            return CanonicalData(Account(id="SYNTH", currency="GBP"), Statement(), ())

    def broken_default():
        pytest.fail("unselected default was invoked")

    registry = ParserRegistry()
    registry.register(
        format="csv", implementation="default", factory=broken_default, default=True
    )
    for identity in ("one", "two"):
        registry.register(
            format="csv",
            implementation=identity,
            factory=lambda identity=identity: Adapter(identity),
        )
    monkeypatch.setattr(api, "_default_registry", lambda: registry)
    source = b"Booking Date,Amount,Currency\n2026-10-01,1.00,GBP\n"
    assert compare(source, implementations=["one", "two", "one"]).matches
    assert seen == ["one", "two"]
    with pytest.raises(ComparisonError):
        compare(source, implementations=[])


def test_compare_applies_csv_options_to_each_backend(monkeypatch):
    pytest.importorskip("bankstatementparser")
    from bankparser import CsvOptions, comparison

    original_parse = comparison.parse
    results = []

    def record_parse(*args, **kwargs):
        result = original_parse(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(comparison, "parse", record_parse)
    source = b'Booking Date,Amount,Currency\n04/05/2026,"1,234",GBP\n'
    report = comparison.compare(source, csv_options=CsvOptions(".", ",", "%d/%m/%Y"))
    assert report.matches
    assert len(results) == 2
    assert all(r.transactions[0].amount == Decimal(1234) for r in results)
    assert all(r.transactions[0].booking_date == date(2026, 5, 4) for r in results)
