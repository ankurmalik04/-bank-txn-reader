"""Collect expected parser failures without losing successful comparison data."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from bankparser import cli, comparison, parse
from bankparser.errors import (
    InputError,
    ParseError,
    ParserDependencyError,
    UnknownImplementationError,
)
from bankparser.serialization import to_primitive

DATA = Path("corpus/csv/basic_valid.csv").read_bytes()


@pytest.fixture
def backend(monkeypatch):
    result = parse(DATA)
    calls = []
    failures = {}
    results = {}

    def run(data, *, implementation, **kwargs):
        calls.append((implementation, data))
        if implementation in failures:
            raise failures[implementation]
        return results.get(implementation, result)

    monkeypatch.setattr(comparison, "parse", run)
    return result, calls, failures, results


def test_partial_success_attempts_all_selected_backends(backend):
    result, calls, failures, results = backend
    failures["bankstatementparser"] = ParseError("PRIVATE-ACCOUNT")
    results["ofxparse"] = replace(result, account=replace(result.account, id="OTHER"))
    report = comparison.compare(
        DATA,
        implementations=["native", "bankstatementparser", "ofxparse", "native"],
        collect_errors=True,
    )
    assert [name for name, _ in calls] == ["native", "bankstatementparser", "ofxparse"]
    assert all(data == DATA for _, data in calls)
    assert not report.complete
    assert not report.matches
    assert report.differences[0].path == "account.id"
    assert list(report.differences[0].values) == ["native", "ofxparse"]
    assert [o.status for o in report.outcomes] == ["success", "error", "success"]
    assert report.outcomes[0].transaction_count == len(result.transactions)
    assert report.outcomes[0].validation_status == result.validation.status
    assert report.outcomes[1].error_code == "PARSE_ERROR"
    assert "PRIVATE-ACCOUNT" not in json.dumps(to_primitive(report))


@pytest.mark.parametrize("successes", [0, 1, 2])
def test_match_requires_all_selected_backends_to_succeed(backend, successes):
    _, _, failures, _ = backend
    selected = ["native", "bankstatementparser"]
    for name in selected[successes:]:
        failures[name] = ParserDependencyError("PRIVATE-DEPENDENCY")
    report = comparison.compare(DATA, implementations=selected, collect_errors=True)
    assert report.complete == (successes == 2)
    assert report.matches == (successes == 2)
    assert report.differences == ()


@pytest.mark.parametrize(
    "failure",
    [
        InputError("bad options"),
        UnknownImplementationError("unknown"),
        RuntimeError("bug"),
    ],
)
def test_configuration_and_programming_errors_are_not_collected(backend, failure):
    _, _, failures, _ = backend
    failures["native"] = failure
    with pytest.raises(type(failure)):
        comparison.compare(
            DATA, implementations=["native", "bankstatementparser"], collect_errors=True
        )


def test_default_api_retains_fail_fast_behavior(backend):
    _, calls, failures, _ = backend
    failures["native"] = ParseError("backend error")
    with pytest.raises(ParseError):
        comparison.compare(DATA, implementations=["native", "bankstatementparser"])
    assert len(calls) == 1


@pytest.mark.parametrize("policy", ["full", "canonical", "redacted-diagnostic"])
@pytest.mark.parametrize("fail_on_diff", [False, True])
def test_cli_partial_report_exits_two_and_retains_outcomes(
    backend, policy, fail_on_diff, capsys
):
    _, _, failures, _ = backend
    failures["bankstatementparser"] = ParseError("PRIVATE-MESSAGE", code="PRIVATE-CODE")
    args = [
        "compare",
        "corpus/csv/basic_valid.csv",
        "--collect-errors",
        "--implementation",
        "native",
        "--implementation",
        "bankstatementparser",
        "--output-policy",
        policy,
    ]
    if fail_on_diff:
        args.append("--fail-on-diff")
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.err == ""
    report = json.loads(output.out)
    assert report["complete"] is False
    assert report["outcomes"][1]["error_code"] == "UNKNOWN_CODE"
    assert "PRIVATE" not in output.out


def test_collected_report_redacts_custom_names_and_keeps_builtin_codes(backend):
    _, _, failures, _ = backend
    failures["PRIVATE-NAME"] = ParseError("PRIVATE-MESSAGE")
    report = comparison.compare(
        DATA, implementations=["native", "PRIVATE-NAME"], collect_errors=True
    )
    output = to_primitive(report, policy="redacted-diagnostic")
    assert output["implementations"] == ["native"]
    assert len(output["outcomes"]) == 1
    assert "PRIVATE" not in json.dumps(output)
