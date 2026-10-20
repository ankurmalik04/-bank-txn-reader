"""Deterministic CSV header detection for bank-statement-shaped files."""

from __future__ import annotations

import csv
import io
import re
import unicodedata

CSV_COLUMN_GROUPS: dict[str, frozenset[str]] = {
    "date": frozenset({"date", "fecha"}),
    "booking_date": frozenset(
        {
            "bookingdate",
            "transactiondate",
            "buchungstag",
            "dateoperation",
            "fechaoperacion",
        }
    ),
    "value_date": frozenset({"valuedate", "datevaleur", "fechavalor"}),
    "description": frozenset(
        {
            "description",
            "details",
            "memo",
            "narrative",
            "payee",
            "name",
            "verwendungszweck",
            "libelle",
            "concepto",
            "descripcion",
        }
    ),
    "amount": frozenset(
        {
            "amount",
            "transactionamount",
            "betrag",
            "value",
            "sum",
            "montant",
            "importe",
        }
    ),
    "debit": frozenset(
        {
            "debit",
            "withdrawal",
            "outflow",
            "soll",
            "cargo",
            "adeudo",
            "debito",
        }
    ),
    "credit": frozenset(
        {
            "credit",
            "deposit",
            "inflow",
            "haben",
            "abono",
            "ingreso",
            "credito",
        }
    ),
    "balance": frozenset({"balance", "runningbalance", "solde", "saldo"}),
    "currency": frozenset({"currency", "ccy", "devise", "divisa", "moneda"}),
    "account_id": frozenset({"account", "accountnumber", "iban", "compte", "cuenta"}),
    "transaction_id": frozenset({"id", "transactionid"}),
    "reference": frozenset({"reference", "ref", "referencia"}),
}

_DELIMITERS = (",", ";", "\t", "|")


def normalize_csv_header(name: str) -> str:
    """Normalize a CSV header for deterministic synonym matching."""
    folded = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", folded.lower())


def detect_csv_columns(data: bytes) -> dict[str, str]:
    """Return recognized logical fields keyed to their original source headers."""
    header = _best_header(data)
    if header is None:
        return {}

    matched: dict[str, str] = {}
    for source_header in header:
        normalized = normalize_csv_header(source_header)
        for logical_name, candidates in CSV_COLUMN_GROUPS.items():
            if logical_name not in matched and normalized in candidates:
                matched[logical_name] = source_header
                break
    return matched


def looks_like_csv(data: bytes) -> bool:
    """Return True for a conservative bank-statement-shaped CSV header."""
    matched = detect_csv_columns(data)
    has_amount = "amount" in matched or "debit" in matched or "credit" in matched
    has_context = any(
        name in matched
        for name in ("date", "booking_date", "value_date", "description", "account_id")
    )
    return has_amount and has_context and len(matched) >= 2


def _best_header(data: bytes) -> tuple[str, ...] | None:
    detected = csv_header(data)
    return detected[1] if detected else None


def csv_header(data: bytes) -> tuple[str, tuple[str, ...]] | None:
    """Return the delimiter and headers used by content detection."""
    try:
        with io.TextIOWrapper(
            io.BytesIO(data), encoding="utf-8-sig", newline=""
        ) as source:
            first_line = next((line for line in source if line.strip()), None)
    except UnicodeDecodeError:
        return None

    if first_line is None:
        return None

    best: tuple[str, tuple[str, ...]] | None = None
    best_score = (-1, -1)
    for delimiter in _DELIMITERS:
        try:
            row = next(csv.reader([first_line], delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        headers = tuple(cell.strip() for cell in row)
        if len(headers) < 2:
            continue
        recognized = sum(
            1
            for header in headers
            if any(
                normalize_csv_header(header) in candidates
                for candidates in CSV_COLUMN_GROUPS.values()
            )
        )
        score = (recognized, len(headers))
        if score > best_score:
            best = delimiter, headers
            best_score = score

    return best
