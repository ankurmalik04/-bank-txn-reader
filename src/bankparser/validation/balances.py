"""Core canonical validation checks."""

from __future__ import annotations

from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext
from itertools import chain

from bankparser.models import (
    Account,
    Statement,
    Transaction,
    ValidationCheck,
    ValidationResult,
    ValidationStatus,
)


def validate(
    account: Account,
    statement: Statement,
    transactions: tuple[Transaction, ...],
) -> ValidationResult:
    """Run independent invariant checks on canonical data."""
    numeric_check = _numeric_finiteness_check(statement, transactions)
    checks = [
        _balance_check(
            statement,
            transactions,
            numerics_finite=numeric_check.status == "passed",
        ),
        _currency_check(account, statement, transactions),
        numeric_check,
        _statement_date_check(statement),
        _transaction_currency_check(transactions),
        _transaction_date_check(statement, transactions, "booking_date"),
        _transaction_date_check(statement, transactions, "value_date"),
        _account_identity_check(account),
    ]
    status: ValidationStatus
    if any(check.status == "failed" for check in checks):
        status = "failed"
    elif any(check.status == "skipped" for check in checks):
        status = "warning"
    else:
        status = "passed"
    return ValidationResult(status=status, checks=tuple(checks))


def _transaction_currency_check(
    transactions: tuple[Transaction, ...],
) -> ValidationCheck:
    missing = [
        str(i) for i, tx in enumerate(transactions) if not (tx.currency or "").strip()
    ]
    return ValidationCheck(
        code="TRANSACTION_CURRENCIES",
        status="skipped" if missing else "passed",
        message="Missing transaction currencies at indices: " + ", ".join(missing)
        if missing
        else "Every transaction has a currency (empty activity is complete)",
    )


def _transaction_date_check(
    statement: Statement, transactions: tuple[Transaction, ...], field: str
) -> ValidationCheck:
    code = (
        "TRANSACTION_BOOKING_DATES"
        if field == "booking_date"
        else "TRANSACTION_VALUE_DATES"
    )
    if not transactions:
        return ValidationCheck(code, "passed", "No transactions require date checks")
    start, end = statement.start_date, statement.end_date
    if start is not None and end is not None and start > end:
        return ValidationCheck(code, "skipped", "Statement period is reversed")
    missing, outside = [], []
    for i, transaction in enumerate(transactions):
        value = getattr(transaction, field)
        if value is None:
            missing.append(str(i))
        elif (start is not None and value < start) or (end is not None and value > end):
            outside.append(str(i))
    if outside:
        return ValidationCheck(
            code,
            "failed" if field == "booking_date" else "skipped",
            f"{field} outside inclusive known statement bounds at indices: "
            + ", ".join(outside)
            + (
                "; value-date settlement exceptions require review"
                if field == "value_date"
                else ""
            ),
        )
    if missing or start is None or end is None:
        return ValidationCheck(
            code,
            "skipped",
            "Both period bounds and all transaction dates are required; missing date indices: "
            + (", ".join(missing) or "none"),
        )
    return ValidationCheck(
        code, "passed", f"All {field} values lie within the inclusive statement period"
    )


def _statement_date_check(statement: Statement) -> ValidationCheck:
    if statement.start_date is None or statement.end_date is None:
        return ValidationCheck(
            code="STATEMENT_DATE_ORDER",
            status="skipped",
            message="Both statement date bounds are required to check their order",
        )
    valid = statement.start_date <= statement.end_date
    return ValidationCheck(
        code="STATEMENT_DATE_ORDER",
        status="passed" if valid else "failed",
        message="Statement start date does not exceed end date"
        if valid
        else "Statement start date exceeds end date",
        expected=f"start_date <= {statement.end_date.isoformat()}",
        actual=statement.start_date.isoformat(),
    )


def _account_identity_check(account: Account) -> ValidationCheck:
    present = bool((account.id or "").strip() or (account.iban or "").strip())
    return ValidationCheck(
        code="ACCOUNT_IDENTITY",
        status="passed" if present else "skipped",
        message="An account identifier is available (not independently verified)"
        if present
        else "Account identity is missing; select and verify the destination account",
    )


def _numeric_finiteness_check(
    statement: Statement,
    transactions: tuple[Transaction, ...],
) -> ValidationCheck:
    invalid: list[str] = []
    for index, transaction in enumerate(transactions):
        if not transaction.amount.is_finite():
            invalid.append(f"transactions[{index}].amount")
    if (
        statement.opening_balance is not None
        and not statement.opening_balance.is_finite()
    ):
        invalid.append("statement.opening_balance")
    if (
        statement.closing_balance is not None
        and not statement.closing_balance.is_finite()
    ):
        invalid.append("statement.closing_balance")

    if invalid:
        return ValidationCheck(
            code="FINITE_AMOUNTS",
            status="failed",
            message=f"Non-finite decimal values detected: {', '.join(invalid)}",
        )
    return ValidationCheck(
        code="FINITE_AMOUNTS",
        status="passed",
        message="All canonical monetary values are finite decimals",
    )


def _balance_check(
    statement: Statement,
    transactions: tuple[Transaction, ...],
    *,
    numerics_finite: bool,
) -> ValidationCheck:
    if statement.opening_balance is None or statement.closing_balance is None:
        return ValidationCheck(
            code="BALANCE_RECONCILIATION",
            status="skipped",
            message="Opening and closing balances are both required",
        )
    if not numerics_finite:
        return ValidationCheck(
            code="BALANCE_RECONCILIATION",
            status="skipped",
            message="Balance reconciliation requires finite monetary values",
        )

    # Cover every input digit, fractional scale and possible carry without
    # depending on the application's Decimal context. All values are finite here.
    minimum_exponent = 0
    maximum_adjusted = 0
    for value in chain(
        (statement.opening_balance,), (tx.amount for tx in transactions)
    ):
        minimum_exponent = min(minimum_exponent, int(value.as_tuple().exponent))
        maximum_adjusted = max(maximum_adjusted, value.adjusted())
    precision = (
        maximum_adjusted - minimum_exponent + 1 + len(str(len(transactions) + 1))
    )
    with localcontext(Context(prec=precision, Emin=MIN_EMIN, Emax=MAX_EMAX)):
        actual = statement.opening_balance + sum(
            (tx.amount for tx in transactions), start=Decimal(0)
        )
    expected = statement.closing_balance
    if actual == expected:
        return ValidationCheck(
            code="BALANCE_RECONCILIATION",
            status="passed",
            message="Opening balance plus transactions equals closing balance",
            expected=str(expected),
            actual=str(actual),
        )
    return ValidationCheck(
        code="BALANCE_RECONCILIATION",
        status="failed",
        message="Opening balance plus transactions does not equal closing balance",
        expected=str(expected),
        actual=str(actual),
    )


def _currency_check(
    account: Account,
    statement: Statement,
    transactions: tuple[Transaction, ...],
) -> ValidationCheck:
    currencies = {
        tx.currency
        for tx in transactions
        if tx.currency is not None and tx.currency.strip()
    }
    if account.currency is not None and account.currency.strip():
        currencies.add(account.currency)
    currencies.update(
        currency
        for currency in (
            statement.opening_balance_currency,
            statement.closing_balance_currency,
        )
        if currency is not None and currency.strip()
    )
    if not currencies:
        return ValidationCheck(
            code="CURRENCY_CONSISTENCY",
            status="skipped",
            message="No currency information is available",
        )
    if len(currencies) == 1:
        currency = next(iter(currencies))
        return ValidationCheck(
            code="CURRENCY_CONSISTENCY",
            status="passed",
            message=f"Canonical data uses one currency: {currency}",
        )
    return ValidationCheck(
        code="CURRENCY_CONSISTENCY",
        status="failed",
        message=f"Multiple currencies detected: {', '.join(sorted(currencies))}",
    )
