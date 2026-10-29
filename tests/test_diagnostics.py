from datetime import date
from decimal import Decimal

from bankparser import diagnostics_for
from bankparser.diagnostics import diagnostic_for_error
from bankparser.errors import ParseError
from bankparser.models import (
    Account,
    ParseResult,
    SourceMetadata,
    Statement,
    Transaction,
)
from bankparser.serialization import to_primitive
from bankparser.validation import validate


def test_missing_date_and_currency_have_structured_record_context():
    transactions = (
        Transaction(
            None,
            date(2026, 10, 1),
            Decimal("2.00"),
            None,
            raw={"source_line_start": 12},
        ),
    )
    account = Account(id="SYNTH", currency="GBP")
    statement = Statement(start_date=date(2026, 10, 1), end_date=date(2026, 10, 2))
    result = ParseResult(
        "1.1",
        SourceMetadata("csv", "native", "1", "1"),
        account,
        statement,
        transactions,
        validate(account, statement, transactions),
    )

    diagnostics = {item.code: item for item in diagnostics_for(result)}
    booking = diagnostics["TRANSACTION_BOOKING_DATES"]
    currency = diagnostics["TRANSACTION_CURRENCIES"]
    assert booking.severity == "warning"
    assert booking.record_indices == (0,)
    assert booking.source_locations == ("CSV line 12",)
    assert booking.canonical_field == "transactions.booking_date"
    assert booking.guidance
    assert currency.record_indices == (0,)
    assert currency.source_locations == ("CSV line 12",)
    assert currency.canonical_field == "transactions.currency"


def test_api_diagnostics_for_parser_error_keep_context_and_guidance():
    error = ParseError(
        "Private backend text",
        code="INVALID_CSV",
        location="CSV line 8, amount",
        format="csv",
        record_index=6,
        canonical_field="transactions.amount",
        guidance="Correct the amount cell.",
    )
    diagnostic = diagnostic_for_error(error)
    assert diagnostic.severity == "error"
    assert diagnostic.format == "csv"
    assert diagnostic.record_indices == (6,)
    assert diagnostic.source_locations == ("CSV line 8, amount",)
    assert diagnostic.canonical_field == "transactions.amount"
    assert diagnostic.guidance == "Correct the amount cell."
    assert to_primitive(diagnostic, policy="redacted-diagnostic") == {
        "diagnostic_schema_version": "1",
        "code": "INVALID_CSV",
        "severity": "error",
        "format": "csv",
        "canonical_field": "transactions.amount",
    }


def test_json_error_keeps_legacy_fields_and_adds_versioned_diagnostic(
    capsys, monkeypatch
):
    from bankparser.cli import main

    error = ParseError(
        "Private parser details",
        code="INVALID_CSV",
        location="CSV line 9, amount",
        format="csv",
        record_index=7,
        canonical_field="transactions.amount",
    )

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("bankparser.cli.parse", fail)
    assert main(["statement.csv", "--json-errors"]) == 2
    import json

    payload = json.loads(capsys.readouterr().err)["error"]
    assert payload["code"] == "INVALID_CSV"
    assert payload["message"] == "Private parser details"
    assert payload["location"] == "CSV line 9, amount"
    assert payload["diagnostic"]["diagnostic_schema_version"] == "1"
    assert payload["diagnostic"]["record_indices"] == [7]


def test_cli_include_diagnostics_emits_context_and_redacted_mode_omits_it(
    capsys, tmp_path
):
    source = tmp_path / "statement.csv"
    source.write_text(
        "Booking Date,Value Date,Amount,Currency,Description\n"
        "2026-10-01,2026-10-01,1.00,,Visible\n"
        ",2026-10-02,2.00,,PRIVATE_MARKER_829174\n"
    )
    from bankparser.cli import main

    assert main([str(source), "--include-diagnostics"]) == 0
    full = capsys.readouterr().out
    import json

    parsed = json.loads(full)
    by_code = {item["code"]: item for item in parsed["diagnostics"]}
    assert by_code["TRANSACTION_BOOKING_DATES"]["record_indices"] == [1]
    assert by_code["TRANSACTION_BOOKING_DATES"]["source_locations"] == ["CSV line 3"]
    currency = by_code["TRANSACTION_CURRENCIES"]
    assert currency["record_indices"] == [0, 1]
    assert currency["canonical_field"] == "transactions.currency"

    assert (
        main(
            [
                str(source),
                "--include-diagnostics",
                "--output-policy",
                "redacted-diagnostic",
            ]
        )
        == 0
    )
    redacted = capsys.readouterr().out
    assert "PRIVATE_MARKER_829174" not in redacted
    redacted_payload = json.loads(redacted)
    assert "diagnostics" in redacted_payload
    assert all("record_indices" not in item for item in redacted_payload["diagnostics"])
    assert all(
        "source_locations" not in item for item in redacted_payload["diagnostics"]
    )
