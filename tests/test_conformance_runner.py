"""Independent oracle, evidence integrity and reporting checks for the runner."""

import hashlib
import importlib.util
import json
import runpy
from copy import deepcopy
from decimal import Inexact, localcontext
from pathlib import Path

import pytest

runner = runpy.run_path("scripts/check_conformance.py")
run = runner["run"]
main = runner["main"]
InputError = runner["ConformanceInputError"]
globals_ = run.__globals__
EXAMPLE = Path("examples/conformance/native-csv.manifest.json")


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def sample(tmp_path):
    manifest = json.loads(EXAMPLE.read_text())
    row = manifest["samples"][0]
    source = tmp_path / "source.csv"
    source.write_bytes(Path("corpus/csv/basic_valid.csv").read_bytes())
    expected = tmp_path / "expected.json"
    expected.write_bytes(
        Path("examples/conformance/native-csv.expected.json").read_bytes()
    )
    row["source"], row["expected"] = source.name, expected.name
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    return path


def update(path, *, manifest_edit=None, source_edit=None, expectation_edit=None):
    manifest = json.loads(path.read_text())
    row = manifest["samples"][0]
    source, expected = path.parent / row["source"], path.parent / row["expected"]
    if source_edit:
        source.write_text(source_edit(source.read_text()))
        row["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    if expectation_edit:
        value = json.loads(expected.read_text())
        expectation_edit(value)
        write_json(expected, value)
        row["expected_sha256"] = hashlib.sha256(expected.read_bytes()).hexdigest()
    if manifest_edit:
        manifest_edit(manifest)
    write_json(path, manifest)


def row(path):
    return run(path)["facts"]["samples"][0]


def checks(result):
    return {c["code"]: c["status"] for c in result["checks"]}


@pytest.mark.parametrize(
    "name,extra",
    [
        ("native-csv", None),
        ("mt940", None),
        ("camt053", "bankstatementparser"),
        ("ofx", "ofxparse"),
    ],
)
def test_independent_corpus_examples_conform_without_certification(name, extra):
    if extra and importlib.util.find_spec(extra) is None:
        pytest.skip("requires optional backend")
    result = run(Path("examples/conformance") / (name + ".manifest.json"))
    assert result["facts"]["summary"] == {"passed": 1, "failed": 0, "error": 0}
    sample = result["facts"]["samples"][0]
    assert sample["differences"] == []
    assert sample["counts"] == {
        "expected": 2,
        "actual": 2,
        "missing_count": 0,
        "extra_count": 0,
    }
    assert sample["backend"]["format"] in {"csv", "mt940", "camt053", "ofx"}
    assert "file_name" not in sample["backend"]
    assert "not assessed" in result["facts"]["certification"]
    assert all(
        checks(sample)[code] == "skipped"
        for code in ("PRODUCTION_EVIDENCE", "INDEPENDENT_REVIEW", "HELD_OUT_EVIDENCE")
    )


def test_repeatable_facts_keep_environment_and_timestamp_separate(sample):
    first, second = run(sample), run(sample)
    assert first["facts"] == second["facts"]
    assert first["execution"]["generated_at"] != second["execution"]["generated_at"]
    assert set(first["execution"]) == {
        "generated_at",
        "python",
        "platform",
        "bankparser_version",
    }
    assert first["facts"]["samples"][0]["parser_validation"]["status"] == "warning"
    assert (
        checks(first["facts"]["samples"][0])["ACTUAL_BALANCE_CONSERVATION"] == "skipped"
    )


@pytest.mark.parametrize("target", ["source", "expected"])
def test_tampered_source_or_expected_is_rejected_before_parsing(
    sample, monkeypatch, target
):
    manifest = json.loads(sample.read_text())
    path = sample.parent / manifest["samples"][0][target]
    path.write_bytes(path.read_bytes() + b"\n")

    def forbidden(*args, **kwargs):
        pytest.fail("tampered evidence reached parser")

    monkeypatch.setitem(globals_, "parse", forbidden)
    result = row(sample)
    assert result["status"] == "error"
    assert result["backend"] is None
    assert result["error"]["code"] == "CONFORMANCE_INPUT_ERROR"
    assert "frozen bytes changed" in result["error"]["reason"]


def test_offsetting_amount_errors_fail_even_when_count_and_total_match(sample):
    update(
        sample,
        source_edit=lambda s: s.replace("500.00", "501.00").replace("-18.75", "-19.75"),
    )
    result = row(sample)
    assert result["status"] == "failed"
    assert checks(result)["BOOKED_TOTALS"] == "passed"
    assert checks(result)["TRANSACTION_COUNT"] == "passed"
    amounts = [d for d in result["differences"] if d["path"].endswith(".amount")]
    assert len(amounts) == 2
    assert all(d["category"] == "financial" for d in amounts)
    assert amounts[0]["expected"] == "500.00"
    assert amounts[0]["actual"] == "501.00"


@pytest.mark.parametrize("change", ["sign", "currency", "date", "account", "identity"])
def test_financial_fields_are_checked_independently(sample, change):
    if change == "identity":
        update(
            sample,
            expectation_edit=lambda e: e["transactions"][0].update(
                transaction_id="EXPECTED-ID"
            ),
        )
    else:
        old, new = {
            "sign": ("-18.75", "18.75"),
            "currency": ("GBP", "EUR"),
            "date": ("2026-09-15", "2026-09-16"),
            "account": ("GB75TEST00000000000001", "GB75TEST00000000000002"),
        }[change]
        update(sample, source_edit=lambda s: s.replace(old, new))
    result = row(sample)
    assert result["status"] == "failed"
    assert any(d["category"] == "financial" for d in result["differences"])


@pytest.mark.parametrize("delta", [-1, 1])
def test_count_changes_preserve_order_and_multiplicity(sample, delta):
    def mutate(s):
        lines = s.splitlines()
        return "\n".join(lines[:-1] if delta == -1 else lines + [lines[-1]]) + "\n"

    update(sample, source_edit=mutate)
    result = row(sample)
    assert result["status"] == "failed"
    assert result["counts"]["actual"] == 2 + delta
    assert result["counts"]["missing_count"] == (1 if delta == -1 else 0)
    assert result["counts"]["extra_count"] == (1 if delta == 1 else 0)
    assert checks(result)["TRANSACTION_COUNT"] == "failed"


def test_legitimate_identical_repeats_are_not_deduplicated(sample):
    update(
        sample,
        source_edit=lambda s: s + s.splitlines()[-1] + "\n",
        expectation_edit=lambda e: e["transactions"].append(
            deepcopy(e["transactions"][-1])
        ),
    )
    result = row(sample)
    assert result["status"] == "passed"
    assert result["counts"]["actual"] == 3
    assert result["booked_totals"]["actual"] == [
        {"currency": "GBP", "amount": "462.50"}
    ]


def test_reordering_is_reported_without_identity_rematching(sample):
    update(
        sample,
        source_edit=lambda s: (
            "\n".join([s.splitlines()[0], *s.splitlines()[1:][::-1]]) + "\n"
        ),
    )
    result = row(sample)
    assert result["status"] == "failed"
    assert result["counts"]["actual"] == result["counts"]["expected"]
    assert any(d["path"] == "transactions[0].reference" for d in result["differences"])
    assert "no identity rematching" in result["alignment"]


def test_explicit_metadata_policy_is_reported_not_erased(sample):
    update(
        sample,
        expectation_edit=lambda e: e["transactions"][0].update(reference="SOURCE-REF"),
        manifest_edit=lambda m: m["samples"][0].update(
            policy_differences=[
                {
                    "path": "transactions[0].reference",
                    "reason": "Explicit canonical reference priority",
                }
            ]
        ),
    )
    result = row(sample)
    assert result["status"] == "passed"
    assert len(result["differences"]) == 1
    diff = result["differences"][0]
    assert diff["category"] == "policy"
    assert diff["expected"] == "SOURCE-REF"
    assert diff["actual"] == "SYNTH-PAY-1"
    assert diff["policy_reason"]


@pytest.mark.parametrize(
    "path",
    [
        "transactions[0].amount",
        "account.id",
        "transactions[0].unknown",
        "transactions.length",
    ],
)
def test_policies_cannot_hide_financial_or_unknown_fields(sample, monkeypatch, path):
    update(
        sample,
        manifest_edit=lambda m: m["samples"][0].update(
            policy_differences=[{"path": path, "reason": "Cannot suppress this"}]
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("invalid policy reached parser")

    monkeypatch.setitem(globals_, "parse", forbidden)
    assert row(sample)["status"] == "error"


def test_plain_metadata_mismatch_is_not_silently_accepted(sample):
    update(
        sample,
        expectation_edit=lambda e: e["transactions"][0].update(description="<missing>"),
    )
    result = row(sample)
    assert result["status"] == "failed"
    difference = next(
        d for d in result["differences"] if d["path"] == "transactions[0].description"
    )
    assert difference["category"] == "metadata"
    assert difference["expected_present"] and difference["actual_present"]
    assert difference["expected"] == "<missing>"


@pytest.mark.parametrize(
    "amount", ["500.000", "500.00000000000000000000000000000000000000000000000"]
)
def test_numeric_scale_equivalence_and_hostile_context(sample, amount):
    update(
        sample, expectation_edit=lambda e: e["transactions"][0].update(amount=amount)
    )
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        before = context.copy()
        assert row(sample)["status"] == "passed"
        assert before.flags == context.flags
        assert before.traps == context.traps


@pytest.mark.parametrize(
    "value", [1.5, "NaN", "Infinity", "1e3", "+1", "1,234", "01", "1\n"]
)
def test_invalid_expected_amounts_are_explicit_input_errors(sample, value):
    update(sample, expectation_edit=lambda e: e["transactions"][0].update(amount=value))
    result = row(sample)
    assert result["status"] == "error"
    assert "plain exact decimal" in result["error"]["reason"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(unknown=True),
        lambda m: m.update(manifest_schema_version="2"),
        lambda m: m.update(samples=[]),
        lambda m: m["samples"].append(deepcopy(m["samples"][0])),
        lambda m: m["profile"].update(format=[]),
        lambda m: m["profile"].update(csv_options={"python": "no execution"}),
        lambda m: m["profile"].update(csv_options={"date_format": []}),
        lambda m: m["samples"][0]["evidence"].update(
            independent_reviewer="independent synthetic corpus authors"
        ),
        lambda m: m["samples"][0]["evidence"].update(held_out_untouched=True),
        lambda m: m["samples"][0]["evidence"].update(held_out_untouched=1),
        lambda m: m["samples"][0].update(source_sha256="not-a-digest"),
        lambda m: m["samples"][0]["evidence"].update(permission=""),
    ],
)
def test_manifest_schema_rejects_ambiguous_or_unproven_configuration(sample, mutation):
    update(sample, manifest_edit=mutation)
    with pytest.raises(InputError):
        run(sample)


@pytest.mark.parametrize(
    "data", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b"\xff", b"not json"]
)
def test_strict_json_errors(sample, data):
    sample.write_bytes(data)
    with pytest.raises(InputError):
        run(sample)


def test_read_bounds_and_missing_files_are_explicit(sample, monkeypatch):
    monkeypatch.setitem(globals_, "LIMIT", 20)
    with pytest.raises(InputError, match="exceeds"):
        run(sample)
    with pytest.raises(InputError, match="cannot read"):
        run(sample.parent / "absent.json")


def test_missing_source_and_parse_error_do_not_expose_payloads(sample):
    update(sample, source_edit=lambda _: "secret invalid source payload")
    result = row(sample)
    assert result["status"] == "error"
    assert result["error"]["code"] == "UNSUPPORTED_FORMAT"
    assert "secret" not in json.dumps(result)
    (sample.parent / "source.csv").unlink()
    assert row(sample)["error"]["reason"] == "source: cannot read file"


def test_different_profile_format_and_canonical_schema_are_rejected(sample):
    update(sample, manifest_edit=lambda m: m["profile"].update(format="mt940"))
    assert row(sample)["status"] == "error"
    update(
        sample, expectation_edit=lambda e: e.update(canonical_schema_version="future")
    )
    assert "canonical schema" in row(sample)["error"]["reason"]


def test_declared_second_review_and_held_out_are_recorded_without_certification(sample):
    def evidence(m):
        m["samples"][0]["evidence"].update(
            kind="production",
            cohort="held-out",
            independent_reviewer="Second reviewer",
            held_out_untouched=True,
        )

    update(sample, manifest_edit=evidence)
    result = run(sample)
    assert all(
        checks(result["facts"]["samples"][0])[c] == "passed"
        for c in ["PRODUCTION_EVIDENCE", "INDEPENDENT_REVIEW", "HELD_OUT_EVIDENCE"]
    )
    assert "not assessed" in result["facts"]["certification"]


def test_multisample_errors_do_not_hide_other_samples(sample):
    def add(m):
        other = deepcopy(m["samples"][0])
        other.update(id="missing-source", source="missing.csv")
        m["samples"].append(other)

    update(sample, manifest_edit=add)
    report = run(sample)
    assert report["facts"]["summary"] == {"passed": 1, "failed": 0, "error": 1}
    assert [r["id"] for r in report["facts"]["samples"]] == [
        "basic-valid-native-csv",
        "missing-source",
    ]


@pytest.mark.parametrize(
    "outcome,exit_code", [("passed", 0), ("failed", 1), ("error", 2)]
)
def test_cli_outputs_and_exit_codes(sample, tmp_path, capsys, outcome, exit_code):
    if outcome == "failed":
        update(sample, source_edit=lambda s: s.replace("500.00", "501.00"))
    elif outcome == "error":
        (tmp_path / "source.csv").write_bytes(b"tampered")
    output, md = tmp_path / "report.json", tmp_path / "report.md"
    assert (
        main([str(sample), "--json", str(output), "--markdown", str(md)]) == exit_code
    )
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert json.loads(output.read_text())["facts"]["summary"][outcome] == 1
    rendered = md.read_text()
    assert "INDEPENDENT_REVIEW" in rendered and "skipped" in rendered
    assert "SHA-256" in rendered and "No bank/profile certification" in rendered


def test_stdout_json_and_invalid_manifest_stderr(sample, capsys):
    assert main([str(sample)]) == 0
    assert json.loads(capsys.readouterr().out)["report_schema_version"] == "1"
    sample.write_bytes(b"bad")
    assert main([str(sample)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "CONFORMANCE_INPUT_ERROR"


@pytest.mark.parametrize("which", ["input", "same", "existing", "unwritable"])
def test_outputs_never_overwrite_evidence(sample, tmp_path, capsys, which):
    before = sample.read_bytes()
    out = sample if which == "input" else tmp_path / "out.json"
    args = [str(sample), "--json", str(out)]
    if which == "same":
        args += ["--markdown", str(out)]
    elif which == "existing":
        out.write_text("existing evidence")
    elif which == "unwritable":
        args[-1] = str(tmp_path / "absent-directory" / "out.json")
    assert main(args) == 2
    assert sample.read_bytes() == before
    assert capsys.readouterr().out == ""
    if which == "existing":
        assert out.read_text() == "existing evidence"


def test_markdown_escapes_untrusted_metadata(sample):
    update(
        sample,
        expectation_edit=lambda e: e["transactions"][0].update(
            description="<script>alert(1)</script>|`bad`\nnext"
        ),
    )
    rendered = runner["markdown"](run(sample))
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&#124;" in rendered and "&#96;" in rendered


@pytest.mark.parametrize(
    "edit",
    [
        lambda e: e["account"].pop("id"),
        lambda e: e.update(transactions={}),
        lambda e: e["transactions"][0].update(booking_date="2026-02-30"),
        lambda e: e["transactions"][0].update(booking_date="20260914"),
        lambda e: e["transactions"][0].update(booking_date=20260914),
        lambda e: e["transactions"][0].update(counterparty=None),
        lambda e: e.update(expectation_schema_version="future"),
    ],
)
def test_expectation_schema_errors_are_structured(sample, edit):
    update(sample, expectation_edit=edit)
    result = row(sample)
    assert result["status"] == "error"
    assert result["error"]["code"] == "CONFORMANCE_INPUT_ERROR"


def test_snapshot_is_shared_by_hash_and_parser(sample, monkeypatch):
    original = globals_["parse"]
    seen = []
    source = sample.parent / "source.csv"
    initial = source.read_bytes()

    def changing(data, **kwargs):
        seen.append(data)
        source.write_bytes(b"replaced after snapshot")
        return original(data, **kwargs)

    monkeypatch.setitem(globals_, "parse", changing)
    result = row(sample)
    assert result["status"] == "passed"
    assert seen == [initial]
    assert result["source_sha256"] == hashlib.sha256(initial).hexdigest()


def test_balance_checks_are_exact_and_skip_incompatible_units():
    core = json.loads(Path("examples/conformance/camt053.expected.json").read_text())
    check = runner["balance_check"]
    assert check(core, "BALANCE")["status"] == "passed"
    core["statement"]["closing_balance"] = "561.26"
    assert check(core, "BALANCE")["status"] == "failed"
    core["statement"]["closing_balance_currency"] = "USD"
    assert check(core, "BALANCE")["status"] == "skipped"
    core["statement"]["closing_balance_currency"] = "GBP"
    core["transactions"][0]["currency"] = None
    assert check(core, "BALANCE")["status"] == "skipped"


def test_currency_totals_do_not_mix_units_or_emit_exponent_numbers():
    values = runner["totals"](
        [
            {"amount": "0.00000001", "currency": "GBP"},
            {"amount": "-0.00000001", "currency": "GBP"},
            {"amount": "10.00", "currency": "USD"},
            {"amount": "2", "currency": None},
        ]
    )
    assert runner["total_rows"](values) == [
        {"currency": None, "amount": "2"},
        {"currency": "GBP", "amount": "0.00000000"},
        {"currency": "USD", "amount": "10.00"},
    ]


def test_invalid_file_names_are_input_errors(sample):
    update(sample, manifest_edit=lambda m: m["samples"][0].update(source="bad\x00file"))
    assert row(sample)["error"]["reason"] == "source: cannot read file"


def test_utf16_json_is_not_silently_accepted(sample):
    sample.write_bytes(sample.read_text().encode("utf-16"))
    with pytest.raises(InputError, match="UTF-8"):
        run(sample)


def test_output_symlink_cannot_replace_frozen_expectation(sample, tmp_path, capsys):
    link = tmp_path / "output.json"
    expected = tmp_path / "expected.json"
    before = expected.read_bytes()
    link.symlink_to(expected)
    assert main([str(sample), "--json", str(link)]) == 2
    assert expected.read_bytes() == before
    assert (
        json.loads(capsys.readouterr().err)["error"]["code"]
        == "CONFORMANCE_INPUT_ERROR"
    )


def test_published_schemas_and_examples_are_in_export_allowlist():
    selected = runpy.run_path("scripts/export_publication.py")["selected"]
    for path in Path("docs/schemas").glob("conformance-*.schema.json"):
        assert selected(path.as_posix())
        assert json.loads(path.read_text())["$schema"].endswith("2020-12/schema")
    assert selected("scripts/check_conformance.py")
    assert selected("docs/conformance.md")
    for path in Path("examples/conformance").glob("*.json"):
        assert selected(path.as_posix())
    assert not selected("docs/reviews/2026-10-24-bank-sample-results.json")


def test_json_nesting_is_bounded(sample):
    value = {}
    for _ in range(70):
        value = {"nested": value}
    update(sample, manifest_edit=lambda m: m["profile"]["settings"].update(extra=value))
    with pytest.raises(InputError, match="nesting"):
        run(sample)


def test_csv_options_are_applied_from_versioned_profile(sample):
    update(
        sample,
        source_edit=lambda s: s.replace("2026-09-14", "14/09/2026").replace(
            "2026-09-15", "15/09/2026"
        ),
        manifest_edit=lambda m: m["profile"].update(
            csv_options={"date_format": "%d/%m/%Y"}
        ),
    )
    assert row(sample)["status"] == "passed"


def test_non_csv_options_and_contradictory_separators_are_rejected(sample):
    update(
        sample,
        manifest_edit=lambda m: m["profile"].update(format="mt940", csv_options={}),
    )
    with pytest.raises(InputError, match="CSV profile"):
        run(sample)
    update(
        sample,
        manifest_edit=lambda m: m["profile"].update(
            format="csv",
            csv_options={"decimal_separator": ".", "grouping_separator": "."},
        ),
    )
    with pytest.raises(InputError, match="csv_options"):
        run(sample)


def test_multi_statement_input_remains_a_reported_parser_error(tmp_path):
    manifest = json.loads(
        Path("examples/conformance/camt053.manifest.json").read_text()
    )
    source = Path("corpus/camt053/multiple_statements.camt053.xml")
    if not source.exists():
        source = next(Path("corpus/camt053").glob("multiple_statements*xml"))
    if importlib.util.find_spec("bankstatementparser") is None:
        pytest.skip("requires camt extra")
    manifest["samples"][0].update(
        source=str(source.resolve()),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected=str(Path("examples/conformance/camt053.expected.json").resolve()),
    )
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    result = row(path)
    assert result["status"] == "error"
    assert result["error"]["code"] == "MULTIPLE_STATEMENTS"
    assert result["counts"] is None
