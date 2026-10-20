"""Adapter for the WoLpH mt-940 package."""

from __future__ import annotations

import importlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.models import Account, Counterparty, Statement, Transaction, Warning
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.mt940.source import source_fields


class WolphMt940Adapter:
    """Map WoLpH mt940 objects into the stable BankParser model."""

    id = "wolph"
    format = "mt940"

    def __init__(self) -> None:
        try:
            self._mt940 = importlib.import_module("mt940")
        except ImportError as exc:
            raise ParserDependencyError(
                "The 'mt-940' package is required for the wolph implementation. "
                + dependency_install_hint()
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._mt940, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        del context
        _, source_transactions = source_fields(data)
        options = self._mt940.Options(
            applicant_iban=True,
            merge_keeps_values=True,
            reversal_sign=True,
            case_insensitive_marks=True,
            timezone_offset=True,
            unbounded_details=True,
            non_swift_free_text=True,
            floor_limit_blank_mark=True,
            strip_bom=True,
            gvc_leading_text=True,
        )
        try:
            statements = self._mt940.parse_statements(data, options=options)
        except Exception as exc:  # library exposes several parse exception types
            raise ParseError(f"WoLpH MT940 parser failed: {exc}") from exc

        if len(statements) != 1:
            raise ParseError(
                f"WoLpH returned {len(statements)} MT940 statement scopes; "
                "BankParser currently expects exactly one"
            )
        native = statements[0]

        account_id = _text(native.data.get("account_identification"))
        opening_native = native.data.get("final_opening_balance")
        closing_native = native.data.get("final_closing_balance")
        opening = _balance(opening_native)
        closing = _balance(closing_native)
        currency = _first_not_none(
            _balance_currency(opening_native),
            _balance_currency(closing_native),
        )

        transactions = tuple(self._map_transaction(tx, currency) for tx in native)
        if len(transactions) != len(source_transactions):
            raise ParseError(
                "MT940 source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
            )
        transaction_currencies = {tx.currency for tx in transactions if tx.currency}
        warnings: list[Warning] = []

        if currency is None and len(transaction_currencies) == 1:
            currency = next(iter(transaction_currencies))
        if currency is None:
            warnings.append(
                Warning("MISSING_CURRENCY", "Statement currency is unavailable")
            )
        if opening is None:
            warnings.append(
                Warning("MISSING_OPENING_BALANCE", "Opening balance is unavailable")
            )
        if closing is None:
            warnings.append(
                Warning("MISSING_CLOSING_BALANCE", "Closing balance is unavailable")
            )

        transaction_dates: list[date] = []
        for transaction in transactions:
            transaction_date = transaction.value_date or transaction.booking_date
            if transaction_date is not None:
                transaction_dates.append(transaction_date)

        opening_date = _balance_date(opening_native)
        closing_date = _balance_date(closing_native)
        statement = Statement(
            id=_text(native.data.get("statement_number")),
            sequence=_text(native.data.get("sequence_number")),
            start_date=opening_date
            or (min(transaction_dates) if transaction_dates else None),
            end_date=closing_date
            or (max(transaction_dates) if transaction_dates else None),
            opening_balance=opening,
            closing_balance=closing,
            opening_balance_currency=_balance_currency(
                native.data.get("final_opening_balance")
            ),
            closing_balance_currency=_balance_currency(
                native.data.get("final_closing_balance")
            ),
        )
        account = Account(id=account_id, iban=None, currency=currency)
        return CanonicalData(
            account=account,
            statement=statement,
            transactions=transactions,
            warnings=tuple(warnings),
        )

    def _map_transaction(
        self, native: Any, statement_currency: str | None
    ) -> Transaction:
        data = native.data
        native_amount = data.get("amount")
        amount = _amount(native_amount)
        currency = _text(getattr(native_amount, "currency", None)) or statement_currency

        value_date = _date(data.get("date"))
        # MT940 entry_date is optional. Do not fabricate a booking date by
        # copying the value date when the source did not provide one.
        booking_date = _date(data.get("entry_date"))
        reference = _first_not_none(
            _text(data.get("customer_reference")),
            _text(data.get("bank_reference")),
        )
        counterparty = Counterparty(
            name=_text(data.get("applicant_name")),
            account_id=_text(data.get("applicant_account")),
            iban=_text(data.get("applicant_iban")),
        )
        raw = {
            key: value
            for key, value in {
                "funds_code": _text(data.get("funds_code")),
                "id": _text(data.get("id")),
                "customer_reference": _text(data.get("customer_reference")),
                "bank_reference": _text(data.get("bank_reference")),
            }.items()
            if value is not None
        }
        return Transaction(
            booking_date=booking_date,
            value_date=value_date,
            amount=amount,
            currency=currency,
            description=_text(data.get("transaction_details")),
            counterparty=counterparty,
            reference=reference,
            transaction_id=None,
            raw=raw,
        )


def _amount(value: Any) -> Decimal:
    amount = getattr(value, "amount", None)
    if isinstance(amount, Decimal) and amount.is_finite():
        return amount
    if isinstance(value, Decimal) and value.is_finite():
        return value
    raise ParseError(f"Parser returned an invalid amount: {value!r}")


def _balance(value: Any) -> Decimal | None:
    if value is None:
        return None
    amount = getattr(value, "amount", None)
    if amount is None:
        return None
    return _amount(amount)


def _balance_currency(value: Any) -> str | None:
    amount = getattr(value, "amount", None)
    return _text(getattr(amount, "currency", None))


def _balance_date(value: Any) -> date | None:
    return _date(getattr(value, "date", None))


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
