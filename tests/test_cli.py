from __future__ import annotations

import importlib.util
import json

import pytest

from bankparser.cli import _normalize_argv, build_parser, main
from bankparser.errors import InputError


def test_implementations_command(capsys) -> None:
    assert main(["implementations", "mt940"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == [
        "bankstatementparser",
        "wolph",
    ]


def test_file_shorthand_is_normalized_to_parse_command() -> None:
    argv = _normalize_argv(["statement.mt940", "--implementation", "wolph"])
    args = build_parser().parse_args(argv)
    assert args.command == "parse"
    assert args.file == "statement.mt940"
    assert args.implementation == "wolph"


def test_compare_command_parses_repeatable_implementations() -> None:
    args = build_parser().parse_args(
        [
            "compare",
            "statement.mt940",
            "--implementation",
            "wolph",
            "--implementation",
            "bankstatementparser",
        ]
    )
    assert args.command == "compare"
    assert args.implementations == ["wolph", "bankstatementparser"]


def test_validation_failures_have_nonzero_exit_but_keep_json(capsys):
    assert main(["corpus/mt940/balance_mismatch.mt940"]) == 3
    captured = capsys.readouterr()
    assert json.loads(captured.out)["validation"]["status"] == "failed"
    assert captured.err == ""


def test_strict_validation_rejects_skipped_checks(capsys):
    assert main(["corpus/mt940/missing_opening_balance.mt940"]) == 0
    capsys.readouterr()
    assert (
        main(["corpus/mt940/missing_opening_balance.mt940", "--strict-validation"]) == 3
    )
    assert json.loads(capsys.readouterr().out)["validation"]["status"] == "warning"


def test_errors_are_structured_on_stderr(capsys, tmp_path):
    empty = tmp_path / "empty.mt940"
    empty.write_bytes(b"")
    assert main([str(empty), "--json-errors"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "INPUT_ERROR"


def test_redacted_cli_output_omits_source_sensitive_markers(capsys, tmp_path):
    marker = "PRIVATE_MARKER_829174"
    path = tmp_path / f"{marker}.csv"
    path.write_text(
        "Booking Date,Description,Amount,Currency,IBAN,Reference\n"
        f"2026-10-01,{marker},-2.50,GBP,{marker},{marker}\n"
    )
    assert main([str(path), "--output-policy", "redacted-diagnostic"]) == 0
    captured = capsys.readouterr()
    assert marker not in captured.out
    report = json.loads(captured.out)
    assert report["transaction_count"] == 1
    assert report["format"] == "csv"
    assert "transactions" not in report


def test_redacted_json_errors_omit_message_and_location(capsys, tmp_path):
    path = tmp_path / "PRIVATE_MARKER_829174.csv"
    assert (
        main(
            [
                str(path),
                "--output-policy",
                "redacted-diagnostic",
                "--json-errors",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "PRIVATE_MARKER_829174" not in captured.err
    assert json.loads(captured.err) == {
        "error": {
            "code": "INPUT_ERROR",
            "diagnostic": {
                "diagnostic_schema_version": "1",
                "code": "INPUT_ERROR",
                "severity": "error",
                "format": None,
                "canonical_field": None,
            },
        }
    }


def test_canonical_cli_policy_omits_raw_but_keeps_canonical_fields(capsys):
    assert (
        main(
            [
                "corpus/csv/basic_valid.csv",
                "--output-policy",
                "canonical",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert "raw" not in result["transactions"][0]
    assert result["transactions"][0]["description"] == "Test contribution"


def test_redacted_compare_and_assess_cli_outputs(capsys, tmp_path):
    marker = "PRIVATE_MARKER_829174"
    path = tmp_path / f"{marker}.csv"
    path.write_text(
        "Booking Date,Description,Amount,Currency,IBAN,Reference,Balance\n"
        f"2026-10-01,{marker},-2.50,GBP,{marker},{marker},97.50\n"
    )
    if importlib.util.find_spec("bankstatementparser") is not None:
        assert (
            main(
                [
                    "compare",
                    str(path),
                    "--output-policy",
                    "redacted-diagnostic",
                ]
            )
            == 0
        )
        comparison = json.loads(capsys.readouterr().out)
        assert marker not in repr(comparison)
        assert "difference_count" in comparison

    status = main(["assess", str(path), "--output-policy", "redacted-diagnostic"])
    captured = capsys.readouterr()
    assert status in {0, 5, 6}
    assert marker not in captured.out
    assessment = json.loads(captured.out)
    assert "duplicate_candidate_count" in assessment


def test_human_errors_are_on_stderr(capsys, tmp_path):
    assert main([str(tmp_path / "missing.mt940")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "INPUT_ERROR" in captured.err


def test_cli_csv_options(capsys):
    assert (
        main(
            [
                "corpus/csv/ambiguous_amount.csv",
                "--decimal-separator",
                ".",
                "--grouping-separator",
                ",",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["transactions"][0]["amount"] == "1234"


def test_runtime_errors_go_to_stderr(monkeypatch, capsys) -> None:
    def fail(*args, **kwargs):
        raise InputError("cannot read statement")

    monkeypatch.setattr("bankparser.cli.parse", fail)

    assert main(["statement.mt940"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "bankparser: INPUT_ERROR: cannot read statement"


def test_csv_without_account_remains_parseable_with_identity_warning(capsys):
    assert (
        main(
            [
                "corpus/csv/ambiguous_amount.csv",
                "--decimal-separator",
                ".",
                "--grouping-separator",
                ",",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["account"]["id"] is None
    assert result["validation"]["status"] == "warning"
    assert "MISSING_ACCOUNT_IDENTITY" in [
        warning["code"] for warning in result["warnings"]
    ]


def test_compare_cli_passes_csv_options_to_both_implementations(tmp_path, capsys):
    import pytest

    pytest.importorskip("bankstatementparser")
    path = tmp_path / "custom.csv"
    path.write_text('Booking Date,Amount,Currency\n04/05/2026,"1,234",GBP\n')
    assert (
        main(
            [
                "compare",
                str(path),
                "--decimal-separator",
                ".",
                "--grouping-separator",
                ",",
                "--date-format",
                "%d/%m/%Y",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["matches"] is True
    assert set(result["implementations"]) == {"native", "bankstatementparser"}


# Exercise the real comparison pipeline through explicitly registered synthetic
# adapters, so these CLI guarantees do not require optional installed backends.
def _comparison_adapters(monkeypatch, mode="match", error=None):
    from datetime import date
    from decimal import Decimal

    from bankparser import api
    from bankparser.models import Account, Statement, Transaction
    from bankparser.parsers.base import CanonicalData
    from bankparser.parsers.registry import ParserRegistry

    class Adapter:
        format = "csv"
        implementation_version = "1"

        def __init__(self, identity):
            self.id = identity

        def parse(self, data, context):
            if self.id == "two" and error is not None:
                raise error
            transactions = tuple(
                Transaction(
                    date(2026, 10, 1),
                    date(2026, 10, 1),
                    Decimal(amount),
                    "GBP",
                    reference=reference,
                )
                for amount, reference in [("10.00", "FIRST"), ("20.00", "SECOND")]
            )
            if self.id == "two":
                from dataclasses import replace

                if mode == "match":
                    transactions = tuple(
                        replace(t, amount=Decimal(str(t.amount) + "0"))
                        for t in transactions
                    )
                elif mode == "amount":
                    transactions = (
                        replace(transactions[0], amount=Decimal("10.001")),
                        transactions[1],
                    )
                elif mode == "reordered":
                    transactions = transactions[::-1]
            return CanonicalData(
                Account(id="SYNTH", currency="GBP"), Statement(), transactions
            )

    registry = ParserRegistry()
    for identity in ["one", "two"]:
        registry.register(
            format="csv",
            implementation=identity,
            factory=lambda identity=identity: Adapter(identity),
            default=identity == "one",
        )
    monkeypatch.setattr(api, "_default_registry", lambda: registry)


def _comparison_args(tmp_path):
    path = tmp_path / "synthetic.csv"
    path.write_text("Booking Date,Amount,Currency\n2026-10-01,10.00,GBP\n")
    return ["compare", str(path), "--implementation", "one", "--implementation", "two"]


@pytest.mark.parametrize("mode", ["match", "amount", "reordered"])
@pytest.mark.parametrize("fail_on_diff", [False, True])
@pytest.mark.parametrize("json_errors", [False, True])
def test_compare_exit_status_and_complete_stdout_report(
    monkeypatch, tmp_path, capsys, mode, fail_on_diff, json_errors
):
    _comparison_adapters(monkeypatch, mode)
    args = _comparison_args(tmp_path)
    if fail_on_diff:
        args.append("--fail-on-diff")
    if json_errors:
        args.append("--json-errors")
    assert main(args) == (4 if fail_on_diff and mode != "match" else 0)
    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["matches"] is (mode == "match")
    assert report["implementations"] == ["one", "two"]
    differences = {d["path"]: d for d in report["differences"]}
    if mode == "match":
        assert differences == {}
    else:
        amount = differences["transactions[0].amount"]
        assert amount["values"] == {
            "one": "10.00",
            "two": "10.001" if mode == "amount" else "20.00",
        }
        assert amount["present"] == {"one": True, "two": True}
        if mode == "reordered":
            assert differences["transactions[0].reference"]["values"] == {
                "one": "FIRST",
                "two": "SECOND",
            }


@pytest.mark.parametrize(
    "kind", ["input", "selection", "parser", "dependency", "unknown", "options"]
)
@pytest.mark.parametrize("fail_on_diff", [False, True])
@pytest.mark.parametrize("json_errors", [False, True])
def test_compare_errors_take_precedence_and_use_stderr_only(
    monkeypatch, tmp_path, capsys, kind, fail_on_diff, json_errors
):
    from bankparser.errors import ParseError, ParserDependencyError

    error = None
    expected_code = {
        "input": "INPUT_ERROR",
        "selection": "COMPARISON_ERROR",
        "parser": "PARSE_ERROR",
        "dependency": "MISSING_DEPENDENCY",
        "unknown": "UNKNOWN_IMPLEMENTATION",
        "options": "INPUT_ERROR",
    }[kind]
    if kind == "parser":
        error = ParseError("synthetic parser failure", location="row[2]")
    elif kind == "dependency":
        error = ParserDependencyError("synthetic missing dependency")
    _comparison_adapters(monkeypatch, error=error)
    args = _comparison_args(tmp_path)
    if kind == "input":
        args[1] = str(tmp_path / "missing.csv")
    elif kind == "selection":
        args = args[:-2]
    elif kind == "unknown":
        args[-1] = "unknown"
    elif kind == "options":
        args += ["--decimal-separator", ".", "--grouping-separator", "."]
    if fail_on_diff:
        args.append("--fail-on-diff")
    if json_errors:
        args.append("--json-errors")
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    if json_errors:
        output = json.loads(captured.err)
        assert set(output) == {"error"}
        assert output["error"]["code"] == expected_code
        assert output["error"]["location"] == ("row[2]" if kind == "parser" else None)
        assert output["error"]["message"]
    else:
        assert captured.err.startswith(f"bankparser: {expected_code}:")
        if kind == "parser":
            assert "(row[2])" in captured.err


@pytest.mark.parametrize("json_errors", [False, True])
@pytest.mark.parametrize("policy", ["full", "canonical", "redacted-diagnostic"])
def test_custom_exception_codes_are_sanitized_only_in_redacted_mode(
    monkeypatch, capsys, policy, json_errors
):
    marker = "GB75TEST00000000000001"

    def fail(*args, **kwargs):
        raise InputError(marker, code=marker, location=marker)

    monkeypatch.setattr("bankparser.cli.parse", fail)
    argv = ["statement.csv", "--output-policy", policy]
    if json_errors:
        argv.append("--json-errors")
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    if policy == "redacted-diagnostic":
        assert marker not in output.err
        if json_errors:
            assert json.loads(output.err) == {
                "error": {
                    "code": "UNKNOWN_CODE",
                    "diagnostic": {
                        "diagnostic_schema_version": "1",
                        "code": "UNKNOWN_CODE",
                        "severity": "error",
                        "format": None,
                        "canonical_field": None,
                    },
                }
            }
        else:
            assert output.err == "bankparser: UNKNOWN_CODE\n"
    else:
        assert marker in output.err


@pytest.mark.parametrize("command", ["parse", "compare", "assess"])
@pytest.mark.parametrize(
    "selector",
    [
        ["--output-policy", "redacted-diagnostic"],
        ["--output-policy=redacted-diagnostic"],
        ["--output-pol", "redacted-diagnostic"],
    ],
)
@pytest.mark.parametrize(
    "invalid",
    [
        ["--format", "GB75TEST00000000000001"],
        ["--GB75TEST00000000000001"],
        ["--header-row", "GB75TEST00000000000001"],
    ],
)
@pytest.mark.parametrize("json_errors", [False, True])
def test_redacted_usage_errors_never_echo_arguments(
    command, selector, invalid, json_errors, capsys
):
    argv = [command, "PRIVATE_MARKER_829174.csv", *invalid, *selector]
    if json_errors:
        argv.append("--json-errors")
    assert main(argv) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "GB75TEST00000000000001" not in output.err
    assert "PRIVATE_MARKER_829174" not in output.err
    if json_errors:
        assert json.loads(output.err) == {"error": {"code": "CLI_USAGE_ERROR"}}
    else:
        assert output.err == "bankparser: CLI_USAGE_ERROR\n"


@pytest.mark.parametrize("policy", ["full", "canonical"])
def test_nonredacted_usage_errors_keep_argparse_behavior(policy, capsys):
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "statement.csv",
                "--output-policy",
                policy,
                "--format",
                "GB75TEST00000000000001",
            ]
        )
    assert caught.value.code == 2
    assert "GB75TEST00000000000001" in capsys.readouterr().err


@pytest.mark.parametrize(
    "selector",
    [
        ["--output-policy=redacted-diagnostic"],
        ["--output-policy", "redacted-diagnostic", "--output-policy", "full"],
    ],
)
def test_redacted_usage_protects_file_shorthand_and_conflicting_policies(
    selector, capsys
):
    assert (
        main(
            [
                "PRIVATE_MARKER_829174.csv",
                "--format",
                "GB75TEST00000000000001",
                *selector,
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "bankparser: CLI_USAGE_ERROR\n"


def test_policy_looking_positional_data_does_not_select_redaction(capsys):
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "statement.csv",
                "--format",
                "GB75TEST00000000000001",
                "--",
                "--output-policy=redacted-diagnostic",
            ]
        )
    assert caught.value.code == 2
    assert "GB75TEST00000000000001" in capsys.readouterr().err
