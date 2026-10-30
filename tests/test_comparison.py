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


@pytest.mark.parametrize("value", ["<missing>", None, ""])
def test_absent_field_differs_from_literal_null_and_empty_text(value):
    from bankparser.serialization import to_primitive

    one = _result("one", None, {})
    two = replace(
        one,
        transactions=one.transactions
        + (replace(one.transactions[0], reference=value),),
    )
    report = compare_results({"one": one, "two": two})
    differences = {d.path: d for d in report.differences}
    difference = differences["transactions[1].reference"]
    assert difference.values == {"one": None, "two": value}
    assert difference.present == {"one": False, "two": True}
    serialized = to_primitive(difference)
    assert serialized == {
        "path": "transactions[1].reference",
        "values": {"one": None, "two": value},
        "present": {"one": False, "two": True},
    }


def test_presence_flags_cover_multiple_implementations_and_json_roundtrip():
    import json

    from bankparser.serialization import to_primitive

    missing = _result("one", None, {})
    present = replace(
        missing,
        transactions=missing.transactions
        + (replace(missing.transactions[0], reference="<missing>"),),
    )
    null = replace(
        present,
        transactions=(
            present.transactions[0],
            replace(present.transactions[1], reference=None),
        ),
    )
    report = compare_results({"absent": missing, "literal": present, "null": null})
    output = json.loads(json.dumps(to_primitive(report)))
    difference = next(
        d for d in output["differences"] if d["path"] == "transactions[1].reference"
    )
    assert difference == {
        "path": "transactions[1].reference",
        "values": {"absent": None, "literal": "<missing>", "null": None},
        "present": {"absent": False, "literal": True, "null": True},
    }
    assert output["matches"] is False


def test_present_null_empty_and_literal_values_keep_their_original_meaning():
    one = _result("one", None, {})
    results = {
        name: replace(
            one, transactions=(replace(one.transactions[0], reference=value),)
        )
        for name, value in [("null", None), ("empty", ""), ("literal", "<missing>")]
    }
    report = compare_results(results)
    assert len(report.differences) == 1
    difference = report.differences[0]
    assert difference.path == "transactions[0].reference"
    assert difference.values == {"null": None, "empty": "", "literal": "<missing>"}
    assert difference.present == {name: True for name in results}


def test_missing_empty_container_is_distinct_from_present_null():
    one = _result("one", None, {})
    two = replace(one, transactions=())
    report = compare_results({"one": one, "two": two})
    difference = next(d for d in report.differences if d.path == "transactions")
    assert difference.values == {"one": None, "two": []}
    assert difference.present == {"one": False, "two": True}


def test_identical_literal_missing_text_does_not_create_a_difference():
    one = _result("one", None, {})
    one = replace(
        one, transactions=(replace(one.transactions[0], reference="<missing>"),)
    )
    report = compare_results({"one": one, "two": one})
    assert report.matches
    assert report.differences == ()


def test_presence_flags_retain_original_monetary_difference_values():
    report = compare_results(
        {"one": _money_result("10.00"), "two": _money_result("10.001")}
    )
    assert all(
        d.values == {"one": "10.00", "two": "10.001"} for d in report.differences
    )
    assert all(d.present == {"one": True, "two": True} for d in report.differences)


def test_cli_serializes_absent_and_literal_missing_without_sentinel_leak(
    monkeypatch, capsys
):
    import json

    from bankparser.cli import main

    one = _result("one", None, {})
    two = replace(
        one,
        transactions=one.transactions
        + (replace(one.transactions[0], reference="<missing>"),),
    )
    report = compare_results({"one": one, "two": two})
    monkeypatch.setattr("bankparser.cli.compare", lambda *args, **kwargs: report)
    assert main(["compare", "synthetic.mt940"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    output = json.loads(captured.out)
    difference = next(
        d for d in output["differences"] if d["path"] == "transactions[1].reference"
    )
    assert difference["values"] == {"one": None, "two": "<missing>"}
    assert difference["present"] == {"one": False, "two": True}


def test_two_argument_difference_construction_remains_supported():
    from bankparser.comparison import ComparisonDifference
    from bankparser.serialization import to_primitive

    difference = ComparisonDifference("account.id", {"one": None, "two": "A"})
    assert to_primitive(difference) == {
        "path": "account.id",
        "values": {"one": None, "two": "A"},
        "present": {},
    }
