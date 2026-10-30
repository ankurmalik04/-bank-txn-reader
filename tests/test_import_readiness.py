"""Destination readiness is additive, conservative and independent of parsing."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import fields, replace
from datetime import date
from decimal import Decimal, Inexact, InvalidOperation, localcontext
from pathlib import Path

import pytest

from bankparser import (
    CsvOptions,
    DestinationAccount,
    ImportPolicy,
    InputError,
    assess_import,
    load_import_policy,
    parse,
)
from bankparser.cli import main
from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
    ValidationCheck,
    ValidationResult,
    Warning,
)
from bankparser.serialization import to_primitive
from bankparser.validation import validate


def result():
    account = Account("SOURCE-A", currency="GBP")
    statement = Statement(
        id="STMT-A",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 2),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("97.50"),
        opening_balance_currency="GBP",
        closing_balance_currency="GBP",
    )
    transactions = (
        Transaction(
            date(2026, 10, 1),
            date(2026, 10, 2),
            Decimal("-2.50"),
            "GBP",
            description="Shop",
            reference="REF-1",
            transaction_id="TX-1",
        ),
    )
    return ParseResult(
        "1.1",
        SourceMetadata("mt940", "synthetic", "1", "0.5.0a2"),
        account,
        statement,
        transactions,
        validate(account, statement, transactions),
    )


def permissive():
    policy = ImportPolicy()
    return replace(
        policy,
        **{
            field.name: "ignore"
            for field in fields(policy)
            if isinstance(getattr(policy, field.name), str)
            and getattr(policy, field.name) in {"review", "block", "ignore"}
        },
    )


def codes(assessment):
    return {reason.code for reason in assessment.reasons}


def missing(base, field):
    if field in {"booking_date", "value_date", "currency", "description", "reference"}:
        return replace(
            base, transactions=(replace(base.transactions[0], **{field: None}),)
        )
    if field == "account_identity":
        return replace(base, account=replace(base.account, id=None))
    if field == "statement_period":
        return replace(base, statement=replace(base.statement, start_date=None))
    return replace(base, statement=replace(base.statement, **{field: None}))


@pytest.mark.parametrize(
    "field",
    [
        "booking_date",
        "value_date",
        "currency",
        "account_identity",
        "description",
        "reference",
        "opening_balance",
        "closing_balance",
        "statement_period",
    ],
)
@pytest.mark.parametrize(
    "action,status", [("ignore", "ready"), ("review", "review"), ("block", "not-ready")]
)
def test_requirement_actions_have_distinct_outcomes(field, action, status):
    policy_name = "transaction_currency" if field == "currency" else field
    policy = replace(ImportPolicy(), **{policy_name: action})
    assessment = assess_import(missing(result(), field), policy)
    assert assessment.status == status
    if action != "ignore":
        assert any(reason.severity == action for reason in assessment.reasons)
        if field in {
            "booking_date",
            "value_date",
            "currency",
            "description",
            "reference",
        }:
            assert assessment.reasons[0].transaction_indices == (0,)


def test_complete_result_is_ready_and_assessment_does_not_mutate_it():
    parsed = result()
    before = deepcopy(to_primitive(parsed))
    assessment = assess_import(parsed)
    assert assessment.status == "ready"
    assert assessment.account_origin == "source"
    assert assessment.reasons == ()
    assert assessment.validation.status == "passed"
    assert assessment.assessment_schema_version == "1"
    assert to_primitive(parsed) == before
    assert json.loads(json.dumps(to_primitive(assessment)))["status"] == "ready"


def test_generic_csv_can_be_ready_with_warning_validation_and_optional_balances():
    parsed = parse("corpus/csv/basic_valid.csv")
    assert parsed.validation.status == "warning"
    assert parsed.statement.opening_balance is None
    assessment = assess_import(parsed)
    assert assessment.status == "ready"
    assert parsed.validation.status == "warning"
    assert assessment.recorded_validation_status == "warning"
    assert any(c.status == "skipped" for c in assessment.validation.checks)


def test_ofx_without_opening_or_value_dates_can_be_ready():
    pytest.importorskip("ofxparse")
    parsed = parse("corpus/ofx/basic_valid.ofx")
    assert parsed.statement.opening_balance is None
    assert all(t.value_date is None for t in parsed.transactions)
    assert assess_import(parsed).status == "ready"
    policy = ImportPolicy(value_date="block", value_date_exempt_formats=("ofx",))
    assert assess_import(parsed, policy).status == "ready"
    assert (
        assess_import(parsed, replace(policy, value_date_exempt_formats=())).status
        == "not-ready"
    )
    assert (
        assess_import(parsed, ImportPolicy(opening_balance="block")).status
        == "not-ready"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "balance",
        "currency",
        "nonfinite",
        "statement-order",
        "booking-range",
        "stored-check",
        "stored-aggregate",
    ],
)
def test_permissive_policy_never_approves_failed_invariants(mutation):
    parsed = result()
    if mutation == "balance":
        parsed = replace(
            parsed, statement=replace(parsed.statement, closing_balance=Decimal(99))
        )
    elif mutation == "currency":
        parsed = replace(parsed, account=replace(parsed.account, currency="EUR"))
    elif mutation == "nonfinite":
        parsed = replace(
            parsed,
            transactions=(replace(parsed.transactions[0], amount=Decimal("sNaN")),),
        )
    elif mutation == "statement-order":
        parsed = replace(
            parsed, statement=replace(parsed.statement, start_date=date(2026, 10, 3))
        )
    elif mutation == "booking-range":
        parsed = replace(
            parsed,
            transactions=(
                replace(parsed.transactions[0], booking_date=date(2026, 9, 1)),
            ),
        )
    elif mutation == "stored-check":
        parsed = replace(
            parsed,
            validation=ValidationResult(
                "passed",
                (ValidationCheck("SOURCE_COUNT", "failed", "SECRET diagnostic"),),
            ),
        )
    else:
        parsed = replace(parsed, validation=ValidationResult("failed"))
    assessment = assess_import(parsed, permissive())
    assert assessment.status == "not-ready"
    assert "FAILED_VALIDATION" in codes(assessment)
    assert "SECRET" not in json.dumps(to_primitive(assessment))


def test_recomputed_validation_detects_post_parse_replacement_even_with_old_pass():
    parsed = result()
    changed = replace(
        parsed, transactions=(replace(parsed.transactions[0], amount=Decimal("-3.50")),)
    )
    assert changed.validation.status == "passed"
    assessment = assess_import(changed, permissive())
    assert assessment.status == "not-ready"
    assert assessment.validation.status == "failed"
    assert assessment.reasons[0].source_code == "BALANCE_RECONCILIATION"


def test_destination_supplies_only_confirmed_context_without_rewriting_source():
    parsed = missing(result(), "account_identity")
    before = to_primitive(parsed)
    destination = DestinationAccount(
        "ledger-bank-7",
        "GBP",
        source_account_id="externally-checked",
        mapping_confirmed=True,
    )
    assessment = assess_import(parsed, destination=destination)
    assert assessment.status == "ready"
    assert assessment.account_origin == "destination-context"
    assert assessment.destination == destination
    assert parsed.account.id is None
    assert to_primitive(parsed) == before
    strict = ImportPolicy(account_identity="block", allow_destination_account=False)
    assert assess_import(parsed, strict, destination=destination).status == "not-ready"


def test_destination_ledger_id_is_not_compared_to_bank_account_id():
    assessment = assess_import(
        result(),
        destination=DestinationAccount(
            "a completely different ledger id", mapping_confirmed=True
        ),
    )
    assert assessment.status == "ready"
    assert assessment.account_origin == "source"
    assert (
        assess_import(result(), destination=DestinationAccount("ledger")).status
        == "review"
    )


@pytest.mark.parametrize(
    "destination",
    [
        DestinationAccount("ledger", source_account_id="OTHER", mapping_confirmed=True),
        DestinationAccount("ledger", "EUR", mapping_confirmed=True),
    ],
)
def test_known_destination_conflicts_cannot_be_ignored(destination):
    assessment = assess_import(result(), permissive(), destination=destination)
    assert assessment.status == "not-ready"
    assert any(reason.code.startswith("DESTINATION_") for reason in assessment.reasons)


def test_iban_conflict_and_missing_currency_are_not_filled_by_destination():
    parsed = replace(
        result(), account=Account("SOURCE-A", "GB75TEST00000000000001", "GBP")
    )
    destination = DestinationAccount(
        "ledger", "GBP", source_iban="DIFFERENT", mapping_confirmed=True
    )
    assert (
        assess_import(parsed, permissive(), destination=destination).status
        == "not-ready"
    )
    parsed = missing(parsed, "currency")
    assessment = assess_import(
        parsed, destination=DestinationAccount("ledger", "GBP", mapping_confirmed=True)
    )
    assert assessment.status == "not-ready"
    assert "MISSING_TRANSACTION_CURRENCY" in codes(assessment)
    assert parsed.transactions[0].currency is None


def test_required_balances_need_source_currency_not_destination_currency():
    parsed = replace(
        result(),
        statement=replace(
            result().statement,
            opening_balance_currency=None,
            closing_balance_currency=None,
        ),
    )
    assessment = assess_import(
        parsed,
        ImportPolicy(opening_balance="block", closing_balance="review"),
        destination=DestinationAccount("ledger", "GBP", mapping_confirmed=True),
    )
    assert assessment.status == "not-ready"
    assert codes(assessment) == {
        "MISSING_OPENING_BALANCE_CURRENCY",
        "MISSING_CLOSING_BALANCE_CURRENCY",
    }


@pytest.mark.parametrize(
    "action,status", [("ignore", "ready"), ("review", "review"), ("block", "not-ready")]
)
def test_configured_currency_requires_explicit_destination_policy(action, status):
    parsed = parse(
        b"Booking Date,Amount,Account\n2026-10-01,1.25,SOURCE-A\n",
        csv_options=CsvOptions(default_currency="GBP"),
    )
    assessment = assess_import(parsed, ImportPolicy(configured_currency=action))
    assert assessment.status == status
    if action != "ignore":
        assert "CONFIGURED_CURRENCY" in codes(assessment)
    assert parsed.transactions[0].raw["source_fields"].get("Currency") is None


@pytest.mark.parametrize(
    "action,status", [("ignore", "ready"), ("review", "review"), ("block", "not-ready")]
)
def test_value_date_settlement_exception_is_separate_from_missing_value_dates(
    action, status
):
    parsed = replace(
        result(),
        transactions=(replace(result().transactions[0], value_date=date(2026, 10, 5)),),
    )
    assessment = assess_import(
        parsed, ImportPolicy(value_date="ignore", value_date_outside_period=action)
    )
    assert assessment.validation.status == "warning"
    assert assessment.status == status
    if action != "ignore":
        assert "VALUE_DATE_OUTSIDE_PERIOD" in codes(assessment)


def duplicate_result(distinct_ids=False):
    parsed = result()
    tx = parsed.transactions[0]
    return replace(
        parsed,
        statement=replace(parsed.statement, closing_balance=Decimal("95.00")),
        transactions=(
            tx,
            replace(tx, transaction_id="TX-2" if distinct_ids else tx.transaction_id),
        ),
    )


@pytest.mark.parametrize(
    "distinct_ids,kind", [(False, "transaction-id"), (True, "similar-record")]
)
def test_duplicate_candidates_preserve_legitimate_repeats_and_require_scoped_review(
    distinct_ids, kind
):
    parsed = duplicate_result(distinct_ids)
    before = to_primitive(parsed)
    assessment = assess_import(parsed)
    assert assessment.status == "review"
    assert len(assessment.duplicate_candidates) == 1
    candidate = assessment.duplicate_candidates[0]
    assert candidate.kind == kind
    assert candidate.transaction_indices == (0, 1)
    approved = assess_import(parsed, reviewed_duplicates=(candidate.fingerprint,))
    assert approved.status == "ready"
    assert approved.duplicate_candidates[0].reviewed
    assert to_primitive(parsed) == before
    assert len(parsed.transactions) == 2
    changed = replace(parsed, account=replace(parsed.account, id="DIFFERENT-ACCOUNT"))
    with pytest.raises(InputError, match="does not apply"):
        assess_import(changed, reviewed_duplicates=(candidate.fingerprint,))
    changed = replace(
        parsed,
        transactions=(
            parsed.transactions[0],
            replace(parsed.transactions[1], description="Changed canonical text"),
        ),
    )
    with pytest.raises(InputError, match="does not apply"):
        assess_import(changed, reviewed_duplicates=(candidate.fingerprint,))


@pytest.mark.parametrize(
    "action,status", [("ignore", "ready"), ("review", "review"), ("block", "not-ready")]
)
def test_duplicate_policy_never_deletes_candidates_or_transactions(action, status):
    parsed = duplicate_result()
    assessment = assess_import(parsed, ImportPolicy(duplicate_candidates=action))
    assert assessment.status == status
    assert len(assessment.duplicate_candidates) == 1
    assert len(parsed.transactions) == 2


@pytest.mark.parametrize("distinct_ids", [False, True])
@pytest.mark.parametrize(
    "destination,policy",
    [
        (DestinationAccount("ledger-B", mapping_confirmed=True), ImportPolicy()),
        (None, ImportPolicy()),
        (DestinationAccount("ledger-A", "GBP", mapping_confirmed=True), ImportPolicy()),
        (
            DestinationAccount(
                "ledger-A", source_account_id="SOURCE-A", mapping_confirmed=True
            ),
            ImportPolicy(),
        ),
        (
            DestinationAccount(
                "ledger-A", source_iban="EXPECTED", mapping_confirmed=True
            ),
            ImportPolicy(),
        ),
        (DestinationAccount("ledger-A"), ImportPolicy()),
        (
            DestinationAccount("ledger-A", mapping_confirmed=True),
            ImportPolicy(id="other"),
        ),
        (
            DestinationAccount("ledger-A", mapping_confirmed=True),
            ImportPolicy(version="2"),
        ),
        (
            DestinationAccount("ledger-A", mapping_confirmed=True),
            ImportPolicy(duplicate_candidates="block"),
        ),
        (
            DestinationAccount("ledger-A", mapping_confirmed=True),
            ImportPolicy(description="block"),
        ),
    ],
)
def test_duplicate_review_cannot_cross_destination_or_policy(
    distinct_ids, destination, policy
):
    parsed = duplicate_result(distinct_ids)
    original_destination = DestinationAccount("ledger-A", mapping_confirmed=True)
    first = assess_import(parsed, destination=original_destination)
    tokens = tuple(c.fingerprint for c in first.duplicate_candidates)
    approved = assess_import(
        deepcopy(parsed),
        ImportPolicy(),
        destination=deepcopy(original_destination),
        reviewed_duplicates=tokens,
    )
    assert approved.status == "ready"
    changed = assess_import(parsed, policy, destination=destination)
    assert changed.result_fingerprint == first.result_fingerprint
    assert not any(c.reviewed for c in changed.duplicate_candidates)
    with pytest.raises(InputError, match="does not apply"):
        assess_import(
            parsed, policy, destination=destination, reviewed_duplicates=tokens
        )


def test_review_without_destination_cannot_authorize_a_destination():
    parsed = duplicate_result()
    token = assess_import(parsed).duplicate_candidates[0].fingerprint
    with pytest.raises(InputError, match="does not apply"):
        assess_import(
            parsed,
            destination=DestinationAccount("ledger-A", mapping_confirmed=True),
            reviewed_duplicates=(token,),
        )


def test_legacy_canonical_only_review_requires_fresh_review():
    parsed = duplicate_result()
    assessment = assess_import(parsed)
    candidate = assessment.duplicate_candidates[0]
    legacy_token = hashlib.sha256(
        json.dumps(
            {
                "version": "1",
                "result": assessment.result_fingerprint,
                "kind": candidate.kind,
                "indices": candidate.transaction_indices,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(InputError, match="does not apply"):
        assess_import(parsed, reviewed_duplicates=(legacy_token,))


def test_review_is_per_group_and_overlapping_groups_remain_visible():
    parsed = result()
    tx = parsed.transactions[0]
    parsed = replace(
        parsed,
        statement=replace(parsed.statement, closing_balance=Decimal("92.50")),
        transactions=(
            tx,
            replace(tx, transaction_id="TX-2"),
            replace(tx, reference="OTHER"),
        ),
    )
    assessment = assess_import(parsed)
    assert [c.transaction_indices for c in assessment.duplicate_candidates] == [
        (0, 1),
        (0, 2),
    ]
    first = assessment.duplicate_candidates[0].fingerprint
    assert assess_import(parsed, reviewed_duplicates=(first,)).status == "review"
    tokens = tuple(c.fingerprint for c in assessment.duplicate_candidates)
    assert assess_import(parsed, reviewed_duplicates=tokens).status == "ready"


def test_duplicate_signatures_use_numeric_amounts_without_context_side_effects():
    parsed = duplicate_result(distinct_ids=True)
    parsed = replace(
        parsed,
        transactions=(
            parsed.transactions[0],
            replace(parsed.transactions[1], amount=Decimal("-2.50000")),
        ),
    )
    with localcontext() as context:
        context.prec = 2
        context.Emax = 9
        context.traps[Inexact] = True
        context.traps[InvalidOperation] = True
        before = context.copy()
        assert assess_import(parsed).status == "review"
        assert context.flags == before.flags and context.traps == before.traps


def test_distinct_references_are_not_duplicate_candidates():
    parsed = duplicate_result(distinct_ids=True)
    parsed = replace(
        parsed,
        transactions=(
            parsed.transactions[0],
            replace(parsed.transactions[1], reference="OTHER"),
        ),
    )
    assert assess_import(parsed).status == "ready"
    assert assess_import(parsed).duplicate_candidates == ()


@pytest.mark.parametrize(
    "action,status", [("ignore", "ready"), ("review", "review"), ("block", "not-ready")]
)
def test_unrecognized_warnings_and_skipped_checks_use_explicit_actions(action, status):
    parsed = replace(
        result(),
        warnings=(Warning("CUSTOM_NOTICE", "SECRET free text"),),
        validation=ValidationResult(
            "warning",
            (ValidationCheck("EXTERNAL_PREREQUISITE", "skipped", "SECRET check"),),
        ),
    )
    assessment = assess_import(
        parsed, ImportPolicy(other_warnings=action, other_incomplete_checks=action)
    )
    assert assessment.status == status
    if action != "ignore":
        assert codes(assessment) == {"PARSER_WARNING", "INCOMPLETE_VALIDATION"}
    assert "SECRET" not in json.dumps(to_primitive(assessment))


def test_unexplained_warning_and_empty_activity_stay_reviewable():
    parsed = replace(result(), validation=ValidationResult("warning"))
    assert "UNEXPLAINED_VALIDATION_WARNING" in codes(assess_import(parsed))
    parsed = replace(
        result(),
        transactions=(),
        statement=replace(result().statement, closing_balance=Decimal("100.00")),
    )
    assert assess_import(parsed).status == "review"
    assert (
        assess_import(parsed, ImportPolicy(empty_activity="ignore")).status == "ready"
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"booking_date": "required"},
        {"account_identity": True},
        {"allow_destination_account": 1},
        {"id": ""},
        {"version": None},
        {"value_date_exempt_formats": ["ofx"]},
        {"value_date_exempt_formats": ("unknown",)},
        {"value_date_exempt_formats": ("ofx", "ofx")},
    ],
)
def test_invalid_policy_options_are_input_errors(kwargs):
    with pytest.raises(InputError):
        ImportPolicy(**kwargs)


@pytest.mark.parametrize(
    "args",
    [
        ("",),
        (None,),
        ("ledger", "US"),
        ("ledger", None, ""),
        ("ledger", None, None, " "),
        ("ledger", None, None, None, 1),
    ],
)
def test_invalid_destination_context_is_rejected(args):
    with pytest.raises(InputError):
        DestinationAccount(*args)


def test_bad_assessment_arguments_and_stale_review_tokens_are_rejected():
    for kwargs in [
        {"policy": {}},
        {"destination": Account("A")},
        {"reviewed_duplicates": []},
        {"reviewed_duplicates": ("bad",)},
        {"reviewed_duplicates": ("0" * 64, "0" * 64)},
    ]:
        with pytest.raises(InputError):
            assess_import(result(), **kwargs)
    with pytest.raises(InputError):
        assess_import({})
    with pytest.raises(InputError):
        assess_import(replace(result(), schema_version="future"))
    with pytest.raises(InputError):
        assess_import(
            replace(result(), source=replace(result().source, format="unknown"))
        )
    with pytest.raises(InputError):
        assess_import(
            replace(
                result(), transactions=(replace(result().transactions[0], amount="1"),)
            )
        )
    with pytest.raises(InputError):
        assess_import(result(), reviewed_duplicates=("0" * 64,))


def test_policy_loader_is_versioned_bounded_strict_json_data(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "policy_schema_version": "1",
                "policy": {
                    "id": "ledger-example",
                    "value_date": "block",
                    "value_date_exempt_formats": ["ofx"],
                },
            }
        )
    )
    policy = load_import_policy(path)
    assert policy.id == "ledger-example" and policy.value_date_exempt_formats == (
        "ofx",
    )
    for payload in [
        b"{}",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b"bad",
        b"\xff",
        b"x" * 65537,
        json.dumps({"policy_schema_version": "2", "policy": {}}).encode(),
        json.dumps(
            {"policy_schema_version": "1", "policy": {"execute": "code"}}
        ).encode(),
        json.dumps(
            {
                "policy_schema_version": "1",
                "policy": {"value_date_exempt_formats": "ofx"},
            }
        ).encode(),
    ]:
        path.write_bytes(payload)
        with pytest.raises(InputError):
            load_import_policy(path)
    with pytest.raises(InputError):
        load_import_policy(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "file,status,exit_code",
    [
        ("corpus/csv/basic_valid.csv", "ready", 0),
        ("corpus/mt940/balance_mismatch.mt940", "not-ready", 6),
    ],
)
def test_cli_assessment_returns_separate_json_and_preserves_parse_contract(
    file, status, exit_code, capsys
):
    before = to_primitive(parse(file))
    assert main(["assess", file, "--json-errors"]) == exit_code
    captured = capsys.readouterr()
    assert captured.err == ""
    output = json.loads(captured.out)
    assert output["status"] == status
    assert output["assessment_schema_version"] == "1"
    assert "transactions" not in output
    assert to_primitive(parse(file)) == before


def test_cli_review_and_confirmed_destination_context(tmp_path, capsys):
    source = tmp_path / "source.csv"
    source.write_text("Booking Date,Amount,Currency\n2026-10-01,1,GBP\n")
    assert main(["assess", str(source)]) == 5
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "review"
    assert output["account_origin"] == "missing"
    assert (
        main(
            [
                "assess",
                str(source),
                "--destination-account",
                "ledger-7",
                "--destination-currency",
                "GBP",
                "--confirm-account-mapping",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["account_origin"] == "destination-context"
    assert output["destination"]["id"] == "ledger-7"
    assert main(["parse", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["account"]["id"] is None


def test_cli_policy_and_profile_options_have_real_pipeline_parity(tmp_path, capsys):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "policy_schema_version": "1",
                "policy": {
                    "id": "test-ledger",
                    "configured_currency": "ignore",
                    "account_identity": "ignore",
                },
            }
        )
    )
    assert (
        main(
            [
                "assess",
                "examples/csv-profiles/legacy-tab.csv",
                "--csv-profile",
                "examples/csv-profiles/legacy-tab.profile.json",
                "--policy",
                str(path),
                "--json-errors",
            ]
        )
        == 6
    )
    output = json.loads(capsys.readouterr().out)
    assert output["policy"]["id"] == "test-ledger"
    assert any(r["code"] == "MISSING_BOOKING_DATE" for r in output["reasons"])
    # Explicit date and currency conventions feed the same parse API.
    source = tmp_path / "source.csv"
    source.write_text("When;Net\n01/10/2026;1,25\n")
    args = [
        "assess",
        str(source),
        "--map",
        "When=booking_date",
        "--map",
        "Net=amount",
        "--date-format",
        "%d/%m/%Y",
        "--decimal-separator",
        ",",
        "--delimiter",
        ";",
        "--default-currency",
        "GBP",
        "--policy",
        str(path),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_cli_duplicate_review_cannot_cross_destinations(tmp_path, capsys):
    source = tmp_path / "repeat.csv"
    source.write_text(
        "Booking Date,Amount,Currency,Account,ID\n"
        "2026-10-01,1,GBP,SOURCE-A,SAME\n2026-10-01,1,GBP,SOURCE-A,SAME\n"
    )
    args = ["assess", str(source), "--confirm-account-mapping", "--json-errors"]
    ledger_a = [*args, "--destination-account", "ledger-A"]
    ledger_b = [*args, "--destination-account", "ledger-B"]
    assert main(ledger_a) == 5
    first = json.loads(capsys.readouterr().out)
    token = first["duplicate_candidates"][0]["fingerprint"]
    assert main([*ledger_a, "--reviewed-duplicate", token]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert main([*ledger_b, "--reviewed-duplicate", token]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "INPUT_ERROR"
    assert main(ledger_b) == 5
    second = json.loads(capsys.readouterr().out)
    assert second["result_fingerprint"] == first["result_fingerprint"]
    candidate = second["duplicate_candidates"][0]
    assert candidate["reviewed"] is False
    assert main([*ledger_b, "--reviewed-duplicate", candidate["fingerprint"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    assert len(parse(source).transactions) == 2


def test_cli_duplicate_review_is_explicit_and_preserves_every_record(tmp_path, capsys):
    source = tmp_path / "repeat.csv"
    source.write_text(
        "Booking Date,Amount,Currency,Account,ID\n2026-10-01,1,GBP,SOURCE-A,SAME\n2026-10-01,1,GBP,SOURCE-A,SAME\n"
    )
    assert main(["assess", str(source), "--json-errors"]) == 5
    assessment = json.loads(capsys.readouterr().out)
    token = assessment["duplicate_candidates"][0]["fingerprint"]
    assert (
        main(["assess", str(source), "--reviewed-duplicate", token, "--json-errors"])
        == 0
    )
    assert (
        json.loads(capsys.readouterr().out)["duplicate_candidates"][0]["reviewed"]
        is True
    )
    assert len(parse(source).transactions) == 2
    source.write_text(source.read_text().replace("1,GBP", "2,GBP"))
    assert (
        main(["assess", str(source), "--reviewed-duplicate", token, "--json-errors"])
        == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "INPUT_ERROR"


@pytest.mark.parametrize(
    "args",
    [
        ["--destination-currency", "GBP"],
        ["--confirm-account-mapping"],
        ["--expected-source-account", "SOURCE-A"],
        ["--expected-source-iban", "IBAN-A"],
        ["--destination-account", "ledger", "--destination-currency", "US"],
        ["--reviewed-duplicate", "bad"],
        ["--policy", "does-not-exist.json"],
    ],
)
def test_cli_invalid_assessment_options_emit_stderr_without_partial_report(
    args, capsys
):
    assert main(["assess", "corpus/csv/basic_valid.csv", *args, "--json-errors"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "INPUT_ERROR"


def test_cli_parse_error_remains_error_not_readiness_result(tmp_path, capsys):
    assert main(["assess", str(tmp_path / "missing.csv"), "--json-errors"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"]["code"] == "INPUT_ERROR"


def test_whitespace_missing_fields_and_default_currency_raw_provenance():
    parsed = replace(
        result(),
        transactions=(
            replace(
                result().transactions[0],
                description="  ",
                reference="\t",
                raw={"csv_configuration": {"currency_origin": "configured-default"}},
            ),
        ),
    )
    assessment = assess_import(
        parsed, ImportPolicy(description="review", reference="block")
    )
    assert assessment.status == "not-ready"
    assert codes(assessment) == {
        "MISSING_DESCRIPTION",
        "MISSING_REFERENCE",
        "CONFIGURED_CURRENCY",
    }


def test_assessment_and_review_fingerprints_are_deterministic():
    first = assess_import(duplicate_result())
    second = assess_import(deepcopy(duplicate_result()))
    assert first == second
    assert to_primitive(first) == to_primitive(second)
    # Raw/backend text is not canonical identity and does not silently affect this token.
    parsed = duplicate_result()
    parsed.transactions[0].raw["arbitrary"] = "backend text"
    assert assess_import(parsed).result_fingerprint == first.result_fingerprint


@pytest.mark.parametrize(
    "stored",
    [
        ValidationResult("unknown"),
        ValidationResult("passed", (ValidationCheck("CUSTOM", "unknown", "invalid"),)),
        {},
    ],
)
def test_unknown_recorded_validation_contract_cannot_be_approved(stored):
    with pytest.raises(InputError):
        assess_import(replace(result(), validation=stored), permissive())


def test_shipped_policy_examples_and_schema_fields_match_public_contract():
    schema = json.loads(Path("docs/schemas/import-policy-v1.schema.json").read_text())
    assert set(schema["$defs"]["policy"]["properties"]) == set(
        ImportPolicy.__dataclass_fields__
    )
    movements = load_import_policy("examples/import-readiness/movements.policy.json")
    reconciled = load_import_policy("examples/import-readiness/reconciled.policy.json")
    assert (
        assess_import(parse("corpus/csv/basic_valid.csv"), movements).status == "ready"
    )
    assert (
        assess_import(parse("corpus/csv/basic_valid.csv"), reconciled).status
        == "not-ready"
    )
    assert (
        assess_import(parse("corpus/mt940/basic_valid.mt940"), reconciled).status
        == "ready"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: replace(
            p,
            statement=replace(p.statement, start_date=None, end_date=None),
            transactions=(replace(p.transactions[0], booking_date="2026-10-01"),),
        ),
        lambda p: replace(p, account=replace(p.account, id=123)),
        lambda p: replace(p, statement=replace(p.statement, opening_balance=100.0)),
        lambda p: replace(p, transactions=(replace(p.transactions[0], raw=None),)),
        lambda p: replace(
            p, transactions=(replace(p.transactions[0], counterparty=None),)
        ),
        lambda p: replace(p, transactions=(replace(p.transactions[0], reference=[]),)),
        lambda p: replace(p, warnings=("not a warning object",)),
        lambda p: replace(
            p,
            validation=ValidationResult(
                "passed", (ValidationCheck(123, "passed", "bad code"),)
            ),
        ),
    ],
)
def test_publicly_constructed_wrong_types_cannot_appear_ready(mutation):
    with pytest.raises(InputError):
        assess_import(mutation(result()), permissive())
