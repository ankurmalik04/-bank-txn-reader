"""Empty OFX source-only warnings remain visible in comparison and CLI output."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

EMPTY = re.sub(
    rb"<STMTTRN>.*?</STMTTRN>",
    b"",
    Path("corpus/ofx/basic_valid.ofx").read_bytes(),
    flags=re.DOTALL,
)
EMPTY_SUMMARY = {"account_id": "GB75TEST00000000000001", "closing_balance": "561.25"}


@pytest.mark.parametrize("collect_errors", [False, True])
def test_real_empty_backend_warning_prevents_apparent_comparison_agreement(
    collect_errors,
):
    pytest.importorskip("bankstatementparser")
    pytest.importorskip("ofxparse")
    from bankparser import compare, parse
    from bankparser.serialization import to_primitive

    result = parse(EMPTY, implementation="bankstatementparser")
    assert result.source.implementation == "bankstatementparser"
    assert result.warnings[-1].code == "OFX_BACKEND_UNVERIFIED"
    assert result.account.id == EMPTY_SUMMARY["account_id"]
    assert result.statement.closing_balance == Decimal(EMPTY_SUMMARY["closing_balance"])
    report = compare(EMPTY, collect_errors=collect_errors)
    assert not report.matches
    assert any(d.path.startswith("warnings[") for d in report.differences)
    assert "OFX_BACKEND_UNVERIFIED" in json.dumps(to_primitive(report))
    if collect_errors:
        assert report.complete
        assert all(o.status == "success" for o in report.outcomes)


@pytest.mark.parametrize("policy", ["full", "canonical", "redacted-diagnostic"])
def test_empty_statement_cli_warning_and_comparison(tmp_path, capsys, policy):
    pytest.importorskip("bankstatementparser")
    pytest.importorskip("ofxparse")
    from bankparser.cli import main

    path = tmp_path / "statement.ofx"
    path.write_bytes(EMPTY)
    assert (
        main(
            [
                "parse",
                str(path),
                "--implementation",
                "bankstatementparser",
                "--output-policy",
                policy,
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["warnings"][-1]["code"] == "OFX_BACKEND_UNVERIFIED"
    assert (
        main(
            [
                "compare",
                str(path),
                "--collect-errors",
                "--fail-on-diff",
                "--output-policy",
                policy,
            ]
        )
        == 4
    )
    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    assert report["complete"] is True
    assert report["matches"] is False
