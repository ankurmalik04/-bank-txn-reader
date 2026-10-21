from datetime import date
from decimal import Decimal, Inexact, localcontext

import pytest

from bankparser.models import Account, Statement, Transaction
from bankparser.validation import validate


def tx(amount: str, currency: str = "GBP") -> Transaction:
    return Transaction(date(2026, 9, 15), date(2026, 9, 15), Decimal(amount), currency)


def test_balance_reconciliation_passes() -> None:
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1174.50"),
        ),
        (tx("-25.50"), tx("200.00")),
    )
    assert result.status == "passed"
    assert result.checks[0].status == "passed"
    assert result.checks[2].code == "FINITE_AMOUNTS"
    assert result.checks[2].status == "passed"


def test_balance_mismatch_fails() -> None:
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("999.99"),
        ),
        (tx("-25.50"),),
    )
    assert result.status == "failed"
    assert result.checks[0].code == "BALANCE_RECONCILIATION"
    assert result.checks[0].actual == "974.50"


def test_missing_balances_gives_warning_not_failure() -> None:
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"), Statement(), (tx("1.00"),)
    )
    assert result.status == "warning"
    assert result.checks[0].status == "skipped"


def test_balance_currencies_are_checked_even_when_arithmetic_agrees():
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal("10.00"),
            closing_balance=Decimal("11.00"),
            opening_balance_currency="GBP",
            closing_balance_currency="USD",
        ),
        (tx("1.00"),),
    )
    assert result.status == "failed"
    assert result.checks[0].status == "passed"
    assert result.checks[1].status == "failed"


def test_multiple_currencies_fail_consistency_check() -> None:
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"),
        Statement(),
        (tx("1.00", "EUR"),),
    )
    assert result.status == "failed"
    assert result.checks[1].code == "CURRENCY_CONSISTENCY"
    assert result.checks[1].status == "failed"


def test_missing_currency_skips_currency_check() -> None:
    result = validate(
        Account(),
        Statement(),
        (Transaction(None, None, Decimal("1.00"), None),),
    )
    assert result.status == "warning"
    assert result.checks[1].status == "skipped"


def test_non_finite_transaction_amount_fails_without_reconciling() -> None:
    result = validate(
        Account(id="SYNTH-ACCOUNT", currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("100.00"),
        ),
        (tx("NaN"),),
    )
    assert result.status == "failed"
    assert result.checks[0].status == "skipped"
    assert result.checks[2].code == "FINITE_AMOUNTS"
    assert result.checks[2].status == "failed"


@pytest.mark.parametrize("precision", [3, 28])
@pytest.mark.parametrize(
    "opening,movements,closing,expected_status",
    [
        (
            "123456789012345678901234567890.12",
            ("0.01",),
            "123456789012345678901234567890.13",
            "passed",
        ),
        (
            "1000000000000000000000000000000.00",
            ("0.01", "-1000000000000000000000000000000.00"),
            "0.01",
            "passed",
        ),
        (
            "123456789012345678901234567890.12",
            ("0.01",),
            "123456789012345678901234567890.12",
            "failed",
        ),
    ],
)
def test_balance_arithmetic_is_exact_and_does_not_modify_caller_context(
    precision, opening, movements, closing, expected_status
):
    with localcontext() as context:
        context.prec = precision
        context.Emax = 9
        context.traps[Inexact] = True
        before = context.copy()
        result = validate(
            Account(id="SYNTH-ACCOUNT", currency="GBP"),
            Statement(
                start_date=date(2026, 9, 14),
                end_date=date(2026, 9, 16),
                opening_balance=Decimal(opening),
                closing_balance=Decimal(closing),
            ),
            tuple(tx(amount) for amount in movements),
        )
        assert result.status == expected_status
        if expected_status == "passed":
            assert Decimal(result.checks[0].actual) == Decimal(closing)
        assert context.prec == before.prec
        assert context.Emax == before.Emax
        assert context.traps == before.traps
        assert context.flags == before.flags


@pytest.mark.parametrize(
    "start,end,status",
    [
        (date(2026, 9, 14), date(2026, 9, 16), "passed"),
        (date(2026, 9, 16), date(2026, 9, 16), "passed"),
        (date(2026, 9, 20), date(2026, 9, 16), "failed"),
        (None, date(2026, 9, 16), "skipped"),
        (date(2026, 9, 14), None, "skipped"),
        (None, None, "skipped"),
    ],
)
def test_statement_date_order_is_independent_of_balance_arithmetic(start, end, status):
    result = validate(
        Account(id="SYNTH", currency="GBP"),
        Statement(
            start_date=start,
            end_date=end,
            opening_balance=Decimal(10),
            closing_balance=Decimal(11),
        ),
        (
            Transaction(
                start or date(2026, 9, 15),
                start or date(2026, 9, 15),
                Decimal(1),
                "GBP",
            ),
        ),
    )
    checks = {check.code: check for check in result.checks}
    assert checks["BALANCE_RECONCILIATION"].status == "passed"
    assert checks["STATEMENT_DATE_ORDER"].status == status
    assert (
        result.status
        == {"passed": "passed", "failed": "failed", "skipped": "warning"}[status]
    )


@pytest.mark.parametrize(
    "identity,iban,status",
    [
        (None, None, "skipped"),
        ("", "", "skipped"),
        ("  ", "\t", "skipped"),
        ("SYNTH", None, "passed"),
        (None, "GB75TEST00000000000001", "passed"),
    ],
)
def test_account_identity_requires_a_nonblank_identifier(identity, iban, status):
    result = validate(
        Account(id=identity, iban=iban, currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal(10),
            closing_balance=Decimal(11),
        ),
        (tx("1"),),
    )
    assert result.checks[-1].code == "ACCOUNT_IDENTITY"
    assert result.checks[-1].status == status
    assert result.status == ("passed" if status == "passed" else "warning")


def test_transaction_dates_are_checked_separately_from_statement_order():
    result = validate(
        Account(id="SYNTH", currency="GBP"),
        Statement(
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 16),
            opening_balance=Decimal(10),
            closing_balance=Decimal(11),
        ),
        (Transaction(date(2026, 9, 20), date(2026, 9, 1), Decimal(1), "GBP"),),
    )
    assert result.status == "failed"
    checks = {c.code: c.status for c in result.checks}
    assert checks["TRANSACTION_BOOKING_DATES"] == "failed"
    assert checks["TRANSACTION_VALUE_DATES"] == "skipped"
