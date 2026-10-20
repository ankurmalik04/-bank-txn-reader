from __future__ import annotations

import json

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
