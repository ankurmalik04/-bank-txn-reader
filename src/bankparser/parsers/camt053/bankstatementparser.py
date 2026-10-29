"""Adapter for bankstatementparser's CAMT.053 implementation."""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bankparser.errors import ParseError, ParserDependencyError, dependency_install_hint
from bankparser.models import Account, Counterparty, Statement, Transaction, Warning
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.scalars import (
    is_missing_scalar,
    validate_amount_text,
)
from bankparser.parsers.scalars import (
    scalar_text as _text,
)


class BankStatementParserCamt053Adapter:
    """Map bankstatementparser CAMT output into the stable BankParser model."""

    id = "bankstatementparser"
    format = "camt053"

    def __init__(self) -> None:
        try:
            self._package = importlib.import_module("bankstatementparser")
            module = importlib.import_module("bankstatementparser.camt_parser")
            self._parser_class = module.CamtParser
        except (ImportError, AttributeError) as exc:
            raise ParserDependencyError(
                "The 'bankstatementparser' package is required for CAMT.053. "
                + dependency_install_hint("camt")
            ) from exc

    @property
    def implementation_version(self) -> str | None:
        return getattr(self._package, "__version__", None)

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        source_name = context.file_name or "statement.xml"
        try:
            parser = self._parser_class.from_bytes(data, source_name=source_name)
            tree = parser.tree
        except Exception as exc:
            raise ParseError(
                f"bankstatementparser CAMT.053 parser failed: {exc}"
            ) from exc

        statements = tree.findall(".//Stmt")
        if len(statements) != 1:
            raise ParseError(
                f"CAMT.053 contains {len(statements)} statements; supply one statement per file",
                code="MULTIPLE_STATEMENTS",
                location="Document/BkToCstmrStmt/Stmt",
            )
        statement_node = statements[0]
        _validate_source(statement_node)
        try:
            transaction_records = parser.get_transactions().to_dict("records")
            balance_records = parser.get_account_balances().to_dict("records")
            summaries = parser.get_summaries()
        except Exception as exc:
            raise ParseError(
                f"bankstatementparser CAMT.053 parser failed: {exc}"
            ) from exc
        source_transactions = _source_transactions(statement_node)
        if len(source_transactions) != len(transaction_records):
            raise ParseError(
                "CAMT.053 source and parser transaction counts differ",
                code="TRANSACTION_COUNT_MISMATCH",
                location="Stmt/Ntry",
            )
        _verify_alignment(source_transactions, transaction_records)

        if len(summaries) != 1:
            raise ParseError(
                "bankstatementparser returned "
                f"{len(summaries)} CAMT statement scopes; BankParser expects one",
                code="MULTIPLE_STATEMENTS",
            )
        summary = summaries[0]
        if not isinstance(summary, Mapping):
            raise ParseError("bankstatementparser returned an invalid CAMT summary")

        currency = _currency(summary.get("currency"))
        transactions = tuple(
            _map_transaction(
                record, statement_currency=currency, source=source_transactions[index]
            )
            for index, record in enumerate(transaction_records)
        )
        if currency is None:
            transaction_currencies = {
                transaction.currency
                for transaction in transactions
                if transaction.currency is not None
            }
            if len(transaction_currencies) == 1:
                currency = next(iter(transaction_currencies))

        opening = _optional_decimal(summary.get("opening_balance"))
        closing = _optional_decimal(summary.get("closing_balance"))
        account_currency = (
            _currency(_element_text(statement_node, "./Acct/Ccy")) or currency
        )
        warnings: list[Warning] = []
        if account_currency is None:
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

        account_id = _text(summary.get("account_id"))
        iban = _element_text(statement_node, "./Acct/Id/IBAN")
        statement_id = _text(summary.get("statement_id")) or _element_text(
            statement_node, "./Id"
        )
        sequence = _first_not_none(
            _element_text(statement_node, "./ElctrncSeqNb"),
            _element_text(statement_node, "./LglSeqNb"),
        )

        return CanonicalData(
            account=Account(id=account_id, iban=iban, currency=account_currency),
            statement=Statement(
                id=statement_id,
                sequence=sequence,
                start_date=_statement_date(
                    statement_node, "FrDtTm", balance_records, "OPBD"
                ),
                end_date=_statement_date(
                    statement_node, "ToDtTm", balance_records, "CLBD"
                ),
                opening_balance=opening,
                closing_balance=closing,
                opening_balance_currency=_balance_currency(statement_node, "OPBD"),
                closing_balance_currency=_balance_currency(statement_node, "CLBD"),
            ),
            transactions=transactions,
            warnings=tuple(warnings),
        )


def _map_transaction(
    record: Mapping[str, Any],
    *,
    statement_currency: str | None,
    source: dict[str, Any],
) -> Transaction:
    amount = _required_decimal(record.get("Amount"))
    debtor = source.get("debtor") or _text(record.get("Debtor"))
    creditor = source.get("creditor") or _text(record.get("Creditor"))
    names = {"debtor": debtor, "creditor": creditor}
    role = (
        "debtor"
        if amount > 0 or (amount == 0 and _text(record.get("DrCr")) == "CRDT")
        else "creditor"
    )
    # Returns can retain only the original payment party. Select one role for
    # all fields, and do not borrow another party's name for an unnamed account.
    if not any(
        (names[role], source.get(f"{role}_account"), source.get(f"{role}_iban"))
    ):
        role = "creditor" if role == "debtor" else "debtor"

    end_to_end_id = _meaningful_reference(record.get("EndToEndId"))
    account_servicer_reference = _text(record.get("AcctSvcrRef")) or source.get(
        "account_servicer_reference"
    )
    reference = _first_not_none(
        end_to_end_id,
        _text(record.get("Reference")),
        account_servicer_reference,
    )
    raw = {
        key: value
        for key, value in {
            "direction": _text(record.get("DrCr")),
            "debtor": debtor,
            "creditor": creditor,
            "end_to_end_id": end_to_end_id,
            "account_servicer_reference": account_servicer_reference,
            **{key: value for key, value in source.items() if key != "_alignment"},
        }.items()
        if value is not None
    }

    return Transaction(
        booking_date=_optional_date(record.get("BookgDt")),
        value_date=_optional_date(record.get("ValDt")),
        amount=amount,
        currency=_currency(record.get("Currency")) or statement_currency,
        description=source.get("description"),
        counterparty=Counterparty(
            name=names[role],
            account_id=source.get(f"{role}_account"),
            iban=source.get(f"{role}_iban"),
        ),
        reference=reference,
        transaction_id=_meaningful_reference(source.get("transaction_id")),
        raw=raw,
    )


def _validate_source(statement: Any) -> None:
    for index, amount in enumerate(statement.iter("Amt"), start=1):
        validate_amount_text(amount.text, location=f"Stmt//Amt[{index}]")
        if Decimal(amount.text).is_signed():
            raise ParseError(
                "CAMT amounts must be non-negative magnitudes; CdtDbtInd supplies the sign",
                code="SIGNED_CAMT_AMOUNT",
                location=f"Stmt//Amt[{index}]",
            )
    for index, entry in enumerate(statement.findall("Ntry"), start=1):
        status = _element_text(entry, "./Sts/Cd") or _element_text(entry, "./Sts")
        if status != "BOOK":
            raise ParseError(
                "CAMT.053 requires booked entries; "
                f"unsupported entry status {status!r}",
                code="UNSUPPORTED_ENTRY_STATUS",
                location=f"Stmt/Ntry[{index}]/Sts",
            )


def _source_transactions(statement: Any) -> list[dict[str, Any]]:
    records = []
    for entry_index, entry in enumerate(statement.findall("Ntry"), start=1):
        details = entry.findall(".//TxDtls")
        for detail_index, detail in enumerate(details or [entry], start=1):
            narrative = detail.findall("./RmtInf/Ustrd") or entry.findall(
                "./RmtInf/Ustrd"
            )
            structured_refs = detail.findall("./RmtInf/Strd//Ref")
            record = {
                "transaction_id": _element_text(detail, "./Refs/TxId"),
                "description": "\n".join(
                    node.text.strip()
                    for node in narrative
                    if node.text and node.text.strip()
                )
                or _element_text(detail, "./AddtlTxInf")
                or _element_text(entry, "./AddtlNtryInf"),
                "account_servicer_reference": _first_not_none(
                    _element_text(detail, "./Refs/AcctSvcrRef"),
                    _element_text(detail, "./AcctSvcrRef"),
                    _element_text(entry, "./AcctSvcrRef"),
                ),
                "structured_references": tuple(
                    node.text.strip()
                    for node in structured_refs
                    if node.text and node.text.strip()
                )
                or None,
                "source_path": f"Stmt/Ntry[{entry_index}]"
                + (f"/NtryDtls/TxDtls[{detail_index}]" if details else ""),
                "payment_references": {
                    node.tag: node.text.strip()
                    for node in detail.findall("./Refs/*")
                    if node.text and node.text.strip()
                }
                or None,
            }
            record["_alignment"] = _source_alignment(
                statement, entry, detail, batched=len(details) > 1
            )
            for role, tag in (("debtor", "Dbtr"), ("creditor", "Cdtr")):
                record[role] = _first_not_none(
                    _element_text(detail, f"./RltdPties/{tag}/Pty/Nm"),
                    _element_text(detail, f"./RltdPties/{tag}/Nm"),
                    _element_text(entry, f"./RltdPties/{tag}/Pty/Nm"),
                    _element_text(entry, f"./RltdPties/{tag}/Nm"),
                )
                for suffix, identifier_path in (
                    ("iban", "IBAN"),
                    ("account", "Othr/Id"),
                ):
                    record[f"{role}_{suffix}"] = _first_not_none(
                        _element_text(
                            detail, f"./RltdPties/{tag}Acct/Id/{identifier_path}"
                        ),
                        _element_text(
                            entry, f"./RltdPties/{tag}Acct/Id/{identifier_path}"
                        ),
                    )
                record[f"{role}_account"] = (
                    record[f"{role}_account"] or record[f"{role}_iban"]
                )
            records.append(record)
    return records


def _source_alignment(
    statement: Any, entry: Any, detail: Any, *, batched: bool
) -> dict[str, Any]:
    amount_node = entry.find("Amt")
    if amount_node is None:
        raise ParseError(
            "CAMT entry lacks a booked amount",
            code="TRANSACTION_ALIGNMENT_MISMATCH",
            location="Stmt/Ntry/Amt",
        )
    currency = _currency(amount_node.get("Ccy")) or _currency(
        _element_text(statement, "./Acct/Ccy")
    )
    amount = _required_decimal(amount_node.text)
    if batched:
        candidates = {
            _required_decimal(node.text)
            for path in ("./Amt", "./AmtDtls/TxAmt/Amt", "./AmtDtls/CntrValAmt/Amt")
            if (node := detail.find(path)) is not None
            and (_currency(node.get("Ccy")) or currency) == currency
        }
        if len(candidates) != 1:
            raise ParseError(
                "Cannot identify a unique booked detail amount",
                code="TRANSACTION_ALIGNMENT_MISMATCH",
                location="Stmt/Ntry/NtryDtls/TxDtls",
            )
        amount = next(iter(candidates))
    direction = _element_text(detail, "./CdtDbtInd") or _element_text(
        entry, "./CdtDbtInd"
    )
    if direction == "DBIT":
        amount = amount.copy_negate()
    record: dict[str, Any] = {
        "Amount": amount,
        "Currency": currency,
        "DrCr": direction,
        "AccountId": _element_text(statement, "./Acct/Id/IBAN")
        or _element_text(statement, "./Acct/Id/Othr/Id"),
        "EndToEndId": _element_text(detail, "./Refs/EndToEndId"),
        "AcctSvcrRef": _element_text(detail, "./Refs/AcctSvcrRef")
        or _element_text(detail, "./AcctSvcrRef"),
    }
    for key, tag in (("BookgDt", "BookgDt"), ("ValDt", "ValDt")):
        record[key] = (
            _element_text(detail, f"./{tag}/Dt")
            or _element_text(detail, f"./{tag}/DtTm")
            or _element_text(entry, f"./{tag}/Dt")
            or _element_text(entry, f"./{tag}/DtTm")
        )
    return record


def _alignment_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        _required_decimal(record.get("Amount")),
        _currency(record.get("Currency")),
        _text(record.get("DrCr")),
        _text(record.get("AccountId")),
        _optional_date(record.get("BookgDt")),
        _optional_date(record.get("ValDt")),
        _meaningful_reference(record.get("EndToEndId")),
        _meaningful_reference(record.get("AcctSvcrRef")),
    )


def _verify_alignment(
    sources: list[dict[str, Any]], records: list[dict[str, Any]]
) -> None:
    source_keys = [_alignment_key(source["_alignment"]) for source in sources]
    if len(set(source_keys)) != len(source_keys):
        raise ParseError(
            "CAMT source records lack distinguishable identities for enrichment",
            code="AMBIGUOUS_TRANSACTION_ALIGNMENT",
            location="Stmt/Ntry",
        )
    for index, (expected, record) in enumerate(zip(source_keys, records), start=1):
        if expected != _alignment_key(record):
            raise ParseError(
                "CAMT backend identity, financial fields or order differ from source",
                code="TRANSACTION_ALIGNMENT_MISMATCH",
                location=sources[index - 1]["source_path"],
            )


def _balance_currency(statement: Any, code: str) -> str | None:
    matches = [
        balance
        for balance in statement.findall("Bal")
        if _element_text(balance, "./Tp/CdOrPrtry/Cd") == code
    ]
    if len(matches) > 1:
        raise ParseError(
            f"Multiple {code} balances cannot be represented",
            code="AMBIGUOUS_BALANCE",
            location=f"Stmt/Bal[{code}]",
        )
    if not matches:
        return None
    amount = matches[0].find("Amt")
    return _currency(amount.get("Ccy")) if amount is not None else None


def _element_text(element: Any, path: str) -> str | None:
    if element is None or not hasattr(element, "findtext"):
        return None
    return _text(element.findtext(path))


def _statement_date(
    statement: Any, bound: str, records: list[dict[str, Any]], balance_code: str
) -> date | None:
    nodes = statement.findall(f"./FrToDt/{bound}")
    if not nodes:
        return _balance_date(records, balance_code)
    value = _text(nodes[0].text)
    try:
        if len(nodes) != 1 or value is None or "T" not in value:
            raise ValueError("Expected one ISO datetime")
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ParseError(
            "Invalid explicit CAMT reporting-period bound",
            code="INVALID_STATEMENT_DATE",
            location=f"Stmt/FrToDt/{bound}",
        ) from exc


def _balance_date(records: list[dict[str, Any]], code: str) -> date | None:
    for record in records:
        if _text(record.get("Code")) == code:
            return _optional_date(record.get("Date"))
    return None


def _required_decimal(value: Any) -> Decimal:
    parsed = _optional_decimal(value)
    if parsed is None:
        raise ParseError(f"Parser returned an invalid amount: {value!r}")
    return parsed


def _optional_decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _optional_date(value: Any) -> date | None:
    if is_missing_scalar(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise ParseError(f"Parser returned an invalid date: {value!r}") from exc


def _meaningful_reference(value: Any) -> str | None:
    text = _text(value)
    if text is None or text.upper() == "NOTPROVIDED":
        return None
    return text


def _currency(value: Any) -> str | None:
    text = _text(value)
    return text.upper() if text is not None else None


def _first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)
