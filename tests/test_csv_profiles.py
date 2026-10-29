"""Five independently invented exporter layouts and their guarded configurations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import date
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

import pytest

from bankparser import (
    CsvOptions,
    CsvProfile,
    InputError,
    ParseError,
    compare,
    load_csv_profile,
    parse,
)
from bankparser.cli import main
from bankparser.serialization import to_primitive

ROOT = Path("examples/csv-profiles")
NAMES = ["mapped-signed", "euro-split", "legacy-tab", "unicode-pipe", "preamble-debit"]


def core(result):
    value = to_primitive(result)
    return {
        "account": value["account"],
        "statement": value["statement"],
        "transactions": [
            {k: v for k, v in t.items() if k != "raw"} for t in value["transactions"]
        ],
    }


@pytest.mark.parametrize("name", NAMES)
def test_profiles_match_independently_authored_full_expectations(name):
    profile = load_csv_profile(ROOT / (name + ".profile.json"))
    source = ROOT / (name + ".csv")
    result = parse(source, csv_profile=profile)
    expected = json.loads((ROOT / (name + ".expected.json")).read_text())
    assert core(result) == {
        k: expected[k] for k in ("account", "statement", "transactions")
    }
    assert result.schema_version == "1.1"
    assert result.source.format == "csv"
    raw = result.transactions[0].raw["csv_configuration"]
    assert raw["profile"] == {
        "id": profile.id,
        "version": "1",
        "sha256": hashlib.sha256(
            (ROOT / (name + ".profile.json")).read_bytes()
        ).hexdigest(),
    }
    assert raw["options"] == profile.options.to_dict()
    if name == "legacy-tab":
        assert raw["currency_origin"] == "configured-default"
        assert any(w.code == "CONFIGURED_CURRENCY" for w in result.warnings)
        assert "Currency" not in result.transactions[0].raw["source_fields"]
    if name == "unicode-pipe":
        assert result.transactions[0].raw["source_line_start"] == 2
        assert result.transactions[0].raw["source_line"] == 3
    if name == "preamble-debit":
        assert raw["header_start_line"] == 4
        assert result.transactions[0].raw["source_line"] == 5


@pytest.mark.parametrize("name", NAMES)
def test_profile_and_options_cli_parity(name, capsys):
    profile = load_csv_profile(ROOT / (name + ".profile.json"))
    source = ROOT / (name + ".csv")
    expected = core(parse(source, csv_profile=profile))
    assert core(parse(source, csv_options=profile.options)) == expected
    assert (
        main(
            [
                "parse",
                str(source),
                "--csv-profile",
                str(ROOT / (name + ".profile.json")),
                "--json-errors",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    actual = json.loads(output.out)
    assert output.err == ""
    assert actual["account"] == expected["account"]
    assert [
        {k: v for k, v in t.items() if k != "raw"} for t in actual["transactions"]
    ] == expected["transactions"]


@pytest.mark.parametrize("name", NAMES)
def test_optional_backend_count_check_and_comparison_share_configuration(name):
    pytest.importorskip("bankstatementparser")
    profile = load_csv_profile(ROOT / (name + ".profile.json"))
    source = ROOT / (name + ".csv")
    native = parse(source, csv_profile=profile)
    alternative = parse(
        source, csv_profile=profile, implementation="bankstatementparser"
    )
    assert native.transactions == alternative.transactions
    assert core(native) == core(alternative)
    assert compare(source, csv_profile=profile).matches


@pytest.mark.parametrize(
    "columns",
    [
        {},
        {"A": "unsupported"},
        {"A": "amount", "B": "amount"},
        {"A": "amount", "B": "debit"},
        {"A": "amount", "B": "credit"},
        {" A": "amount"},
        {"A": []},
        [],
    ],
)
def test_invalid_mappings_fail_before_parsing(columns):
    with pytest.raises(InputError):
        CsvOptions(columns=columns)


def test_mapping_replaces_synonyms_and_is_immutable():
    mapping = {"Posted": "booking_date", "Net": "amount"}
    options = CsvOptions(columns=mapping)
    mapping["Net"] = "credit"
    assert options.columns["Net"] == "amount"
    with pytest.raises(TypeError):
        options.columns["New"] = "description"
    data = b"Posted,Net,Amount\n2026-10-01,-2.25,not a monetary field\n"
    result = parse(data, csv_options=options)
    assert result.transactions[0].amount == Decimal("-2.25")
    assert (
        result.transactions[0].raw["source_fields"]["Amount"] == "not a monetary field"
    )


@pytest.mark.parametrize(
    "data,options,code",
    [
        (
            b"Posted,Net\n2026-10-01,1\n",
            CsvOptions(columns={"Missing": "date", "Net": "amount"}),
            "MISSING_CSV_COLUMN",
        ),
        (
            b"Posted,Net,Net\n2026-10-01,1,1\n",
            CsvOptions(columns={"Posted": "date", "Net": "amount"}),
            "AMBIGUOUS_COLUMNS",
        ),
        (
            b"Booking Date,Date,Amount\n2026-10-01,2026-10-01,1\n",
            CsvOptions(date_role="booking_date"),
            "AMBIGUOUS_COLUMNS",
        ),
        (
            b"Booking Date,Amount\n2026-10-01,1\n",
            CsvOptions(header_row=2),
            "INVALID_CSV_HEADER",
        ),
        (
            b"junk\nDate,Amount\n2026-10-01,1\n",
            CsvOptions(header_search_limit=1),
            "INVALID_CSV_HEADER",
        ),
        (
            b"Date,Amount\nDate,Amount\n2026-10-01,1\n",
            CsvOptions(header_search_limit=3),
            "AMBIGUOUS_CSV_HEADER",
        ),
        (b"Date,Debit,Credit\n2026-10-01,1,2\n", CsvOptions(), "AMBIGUOUS_MOVEMENT"),
        (b"Date,Debit\n2026-10-01,-1\n", CsvOptions(), "SIGNED_DEBIT_CREDIT"),
    ],
)
def test_rejects_ambiguous_missing_or_contradictory_source_fields(data, options, code):
    with pytest.raises(ParseError) as caught:
        parse(data, csv_options=options)
    assert caught.value.code == code


def test_generic_date_role_is_explicit_and_original_date_is_preserved():
    data = b"Date,Amount\n2026-10-01,1\n"
    original = parse(data)
    assert original.transactions[0].booking_date is None
    assert "AMBIGUOUS_DATE_SEMANTICS" in {w.code for w in original.warnings}
    configured = parse(data, csv_options=CsvOptions(date_role="booking_date"))
    assert configured.transactions[0].booking_date == date(2026, 10, 1)
    assert "AMBIGUOUS_DATE_SEMANTICS" not in {w.code for w in configured.warnings}
    assert configured.transactions[0].raw["source_fields"]["Date"] == "2026-10-01"


def test_fallback_fills_only_absent_currency_and_constraint_never_overwrites():
    data = b"Booking Date,Amount,Currency\n2026-10-01,1,EUR\n"
    result = parse(data, csv_options=CsvOptions(default_currency="GBP"))
    assert result.transactions[0].currency == "EUR"
    assert (
        result.transactions[0].raw["csv_configuration"]["currency_origin"] == "source"
    )
    with pytest.raises(ParseError) as caught:
        parse(data, csv_options=CsvOptions(expected_currency="GBP"))
    assert caught.value.code == "CSV_CURRENCY_CONSTRAINT"
    missing = data.replace(b",EUR", b",")
    with pytest.raises(ParseError):
        parse(missing, csv_options=CsvOptions(expected_currency="GBP"))
    filled = parse(
        missing, csv_options=CsvOptions(default_currency="gbp", expected_currency="GBP")
    )
    assert filled.account.currency == "GBP"
    assert filled.transactions[0].raw["source_fields"]["Currency"] == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"default_currency": "US"},
        {"default_currency": True},
        {"expected_currency": "GBP", "default_currency": "EUR"},
        {"date_role": "posted"},
        {"header_row": 0},
        {"header_row": True},
        {"header_row": 10001},
        {"header_search_limit": 201},
        {"header_search_limit": 0},
        {"header_row": 2, "header_search_limit": 10},
        {"encoding": "utf-16"},
        {"encoding": []},
        {"delimiter": ":"},
        {"date_format": []},
        {"date_format": ""},
    ],
)
def test_invalid_conventions_are_input_errors(kwargs):
    with pytest.raises(InputError):
        CsvOptions(**kwargs)


@pytest.mark.parametrize(
    "file",
    [
        "corpus/mt940/basic_valid.mt940",
        "corpus/camt053/basic_valid.camt053.xml",
        "corpus/ofx/basic_valid.ofx",
    ],
)
def test_override_never_reinterprets_recognized_non_csv(file):
    with pytest.raises(InputError):
        parse(file, format="csv")
    with pytest.raises(InputError):
        compare(file, format="csv")


@pytest.mark.parametrize(
    "data",
    [
        b"hello",
        b"product,category\nChair,Furniture\n",
        b"foo,amount\nbar,10\n",
        b"Booking Date,Amount\n2026-10-01,NaN\n",
    ],
)
def test_forced_csv_still_requires_shape_and_finite_amounts(data):
    with pytest.raises(ParseError):
        parse(data, format="csv")


def test_custom_headers_need_declaration_and_csv_overrides_are_bounded():
    data = b"Posted,Net\n2026-10-01,1.25\n"
    with pytest.raises(Exception) as caught:
        parse(data)
    assert caught.value.code == "UNSUPPORTED_FORMAT"
    with pytest.raises(InputError):
        parse(data, format="ofx")
    with pytest.raises(InputError):
        parse(data, csv_options={}, format="csv")
    with pytest.raises(InputError):
        parse(b"x" * (5 * 1024 * 1024 + 1), format="csv")


def test_profile_conflicts_and_strict_json_loading(tmp_path):
    profile = load_csv_profile(ROOT / "mapped-signed.profile.json")
    with pytest.raises(InputError):
        parse(ROOT / "mapped-signed.csv", csv_profile=profile, csv_options=CsvOptions())
    with pytest.raises(InputError):
        compare(
            ROOT / "mapped-signed.csv", csv_profile=profile, csv_options=CsvOptions()
        )
    with pytest.raises(InputError):
        parse(b"anything", csv_profile="path")
    for payload in [
        b"bad",
        b'{"id":1,"id":2}',
        b'{"x":NaN}',
        b"x" * 65537,
        b"{}",
        b"\xff",
    ]:
        path = tmp_path / "bad.json"
        path.write_bytes(payload)
        with pytest.raises(InputError):
            load_csv_profile(path)
    with pytest.raises(InputError):
        load_csv_profile(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "edit",
    [
        lambda p: p.update(profile_schema_version="future"),
        lambda p: p.update(format="ofx"),
        lambda p: p.update(extra="unknown"),
        lambda p: p.update(options=[]),
        lambda p: p["options"].update(execute="arbitrary code"),
        lambda p: p.update(id=[]),
    ],
)
def test_profiles_are_data_only_and_versioned(tmp_path, edit):
    profile = json.loads((ROOT / "mapped-signed.profile.json").read_text())
    edit(profile)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    with pytest.raises(InputError):
        load_csv_profile(path)


def test_cli_explicit_flags_apply_to_parse_and_compare(tmp_path, capsys):
    path = tmp_path / "source.csv"
    path.write_bytes(b"Posted;Net\n01/10/2026;-2,50\n")
    flags = [
        "--map",
        "Posted=booking_date",
        "--map",
        "Net=amount",
        "--date-format",
        "%d/%m/%Y",
        "--decimal-separator",
        ",",
        "--default-currency",
        "GBP",
        "--expected-currency",
        "GBP",
        "--delimiter",
        ";",
        "--format",
        "csv",
    ]
    assert main(["parse", str(path), *flags]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["transactions"][0]["amount"] == "-2.50"
    assert output["transactions"][0]["booking_date"] == "2026-10-01"
    if importlib.util.find_spec("bankstatementparser"):
        assert (
            main(["compare", str(path), *flags, "--fail-on-diff", "--json-errors"]) == 0
        )
        assert json.loads(capsys.readouterr().out)["matches"]


@pytest.mark.parametrize(
    "flags",
    [
        ["--map", "invalid"],
        ["--map", "Amount=amount", "--map", "Amount=credit"],
        [
            "--csv-profile",
            str(ROOT / "mapped-signed.profile.json"),
            "--default-currency",
            "GBP",
        ],
        ["--map", "Amount=unknown"],
        ["--header-row", "0"],
        ["--expected-currency", "US"],
    ],
)
def test_cli_bad_configuration_is_structured_stderr(flags, capsys):
    assert (
        main(["parse", str(ROOT / "mapped-signed.csv"), *flags, "--json-errors"]) == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "INPUT_ERROR"


def test_high_precision_profile_amounts_do_not_inherit_caller_context():
    data = b"Posted,Net\n2026-10-01,123456789012345678901234567890.123456789\n"
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = parse(
            data,
            csv_options=CsvOptions(
                columns={"Posted": "booking_date", "Net": "amount"},
                decimal_separator=".",
            ),
        )
    assert result.transactions[0].amount == Decimal(
        "123456789012345678901234567890.123456789"
    )


def test_profile_serialization_handles_immutable_mapping():
    profile = load_csv_profile(ROOT / "mapped-signed.profile.json")
    serialized = to_primitive(profile)
    assert json.loads(json.dumps(serialized))["options"]["columns"]["Net"] == "amount"


@pytest.mark.parametrize("name", NAMES)
def test_profiles_work_with_frozen_conformance_runner(tmp_path, name):
    runner = __import__("runpy").run_path("scripts/check_conformance.py")["run"]
    profile = load_csv_profile(ROOT / (name + ".profile.json"))
    config = json.loads(
        Path("examples/conformance/native-csv.manifest.json").read_text()
    )
    config["profile"].update(
        id=profile.id, version=profile.version, csv_options=profile.options.to_dict()
    )
    config["profile"]["settings"].update(
        encoding=profile.options.encoding,
        currency=json.loads((ROOT / (name + ".expected.json")).read_text())["account"][
            "currency"
        ],
        date_convention=profile.options.date_format or "ISO dates",
        amount_convention="Explicit signed Amount or debit/credit magnitudes per options",
    )
    source = (ROOT / (name + ".csv")).resolve()
    expected = (ROOT / (name + ".expected.json")).resolve()
    config["samples"][0].update(
        id=name,
        source=str(source),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected=str(expected),
        expected_sha256=hashlib.sha256(expected.read_bytes()).hexdigest(),
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(config))
    report = runner(manifest)
    assert report["facts"]["summary"] == {"passed": 1, "failed": 0, "error": 0}
    assert report["facts"]["samples"][0]["differences"] == []


def test_header_selection_counts_physical_lines_and_rejects_partial_record():
    data = b'"notes\ncontinued"\nPosted,Net\n2026-10-01,1\n'
    options = CsvOptions(
        columns={"Posted": "booking_date", "Net": "amount"}, delimiter=",", header_row=3
    )
    result = parse(data, csv_options=options)
    assert result.transactions[0].raw["csv_configuration"]["header_start_line"] == 3
    assert result.transactions[0].raw["source_line"] == 4
    with pytest.raises(ParseError):
        parse(data, csv_options=replace_options(options, header_row=2))
    # The header begins on line 1 but extends past the bounded search window.
    multiline = b'"Post\ned",Net\n2026-10-01,1\n'
    with pytest.raises(ParseError):
        parse(
            multiline,
            csv_options=CsvOptions(
                columns={"Post\ned": "booking_date", "Net": "amount"},
                header_search_limit=1,
                delimiter=",",
            ),
        )


def replace_options(options, **updates):
    values = options.to_dict()
    values.update(updates)
    return CsvOptions(**values)


def test_header_search_bound_and_legacy_encoding_are_explicit():
    source = (ROOT / "legacy-tab.csv").read_bytes()
    with pytest.raises(ParseError):
        parse(source, csv_options=CsvOptions())
    with pytest.raises(InputError):
        CsvOptions(encoding="auto")
    for encoding in ["windows-1252", "cp1252", "latin-1", "iso-8859-1"]:
        options = load_csv_profile(ROOT / "legacy-tab.profile.json").options
        assert (
            parse(source, csv_options=replace_options(options, encoding=encoding))
            .transactions[0]
            .description
            == "Café"
        )


def test_mapping_source_semantics_do_not_infer_iban_and_scopes_stay_separate():
    options = CsvOptions(
        columns={"Posted": "booking_date", "Net": "amount", "Identifier": "account_id"}
    )
    result = parse(
        b"Posted,Net,Identifier\n2026-10-01,1,GB75TEST00000000000001\n",
        csv_options=options,
    )
    assert result.account.id == "GB75TEST00000000000001"
    assert result.account.iban is None
    data = b"Posted,Net,Local,International\n2026-10-01,1,LOCAL,IBAN-A\n2026-10-02,2,LOCAL,IBAN-B\n"
    with pytest.raises(ParseError) as caught:
        parse(
            data,
            csv_options=CsvOptions(
                columns={
                    "Posted": "booking_date",
                    "Net": "amount",
                    "Local": "account_id",
                    "International": "iban",
                }
            ),
        )
    assert caught.value.code == "MULTIPLE_STATEMENTS"


def test_manual_profile_has_explicit_conventions_without_claimed_file_digest():
    profile = CsvProfile(
        "synthetic-manual",
        "1",
        CsvOptions(columns={"Posted": "booking_date", "Net": "amount"}),
    )
    result = parse(b"Posted,Net\n2026-10-01,1\n", csv_profile=profile)
    assert result.transactions[0].raw["csv_configuration"]["profile"] == {
        "id": "synthetic-manual",
        "version": "1",
        "sha256": None,
    }
    with pytest.raises(InputError):
        CsvProfile("name", "1", {})
    with pytest.raises(InputError):
        CsvProfile("name", "1", CsvOptions(), sha256="bad")


def test_csv_option_and_evidence_schema_fields_stay_aligned():
    schema = json.loads(Path("docs/schemas/csv-profile-v1.schema.json").read_text())
    options = schema["$defs"]["options"]
    assert set(options["properties"]) == set(CsvOptions.__dataclass_fields__)
    for name in [
        "conformance-manifest-v1.schema.json",
        "conformance-report-v1.schema.json",
    ]:
        evidence = json.loads((Path("docs/schemas") / name).read_text())
        assert (
            evidence["$defs"]["profile"]["properties"]["csv_options"]["anyOf"][0]
            == options
        )


@pytest.mark.parametrize(
    "tail,code,line",
    [
        ("2026-10-01,1,extra\n", "INVALID_CSV_ROW", "CSV line 4"),
        ("2026-10-01,not-money\n", "INVALID_AMOUNT", "CSV line 4, column 'Net'"),
    ],
)
def test_configured_row_failures_keep_original_physical_locations(tail, code, line):
    data = ("preamble\n\nPosted,Net\n" + tail).encode()
    with pytest.raises(ParseError) as caught:
        parse(
            data,
            csv_options=CsvOptions(
                columns={"Posted": "booking_date", "Net": "amount"},
                header_row=3,
                delimiter=",",
            ),
        )
    assert caught.value.code == code
    assert caught.value.location == line
