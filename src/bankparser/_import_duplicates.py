"""Intra-result duplicate candidates and stable scoped review fingerprints."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from bankparser._import_policy import DestinationAccount, ImportPolicy
from bankparser.models import ParseResult
from bankparser.serialization import to_primitive


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """An intra-result review candidate, not proof of a duplicate payment."""

    kind: Literal["transaction-id", "similar-record"]
    transaction_indices: tuple[int, ...]
    fingerprint: str
    reviewed: bool = False


def _text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            to_primitive(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _duplicates(
    result: ParseResult,
    fingerprint: str,
    policy: ImportPolicy,
    destination: DestinationAccount | None,
) -> tuple[DuplicateCandidate, ...]:
    ids: dict[str, list[int]] = {}
    signatures: dict[tuple[Any, ...], list[int]] = {}
    for index, tx in enumerate(result.transactions):
        identity = _text(tx.transaction_id)
        if identity:
            ids.setdefault(identity, []).append(index)
        if tx.amount.is_finite():
            signature = (
                tx.booking_date,
                tx.value_date,
                tx.amount,
                _text(tx.currency),
                tx.description,
                tx.reference,
                tx.counterparty.name,
                tx.counterparty.account_id,
                tx.counterparty.iban,
            )
            signatures.setdefault(signature, []).append(index)
    groups: dict[tuple[int, ...], Literal["transaction-id", "similar-record"]] = {}
    for indices in signatures.values():
        if len(indices) > 1:
            groups[tuple(indices)] = "similar-record"
    for indices in ids.values():
        if len(indices) > 1:
            groups[tuple(indices)] = "transaction-id"
    return tuple(
        DuplicateCandidate(
            kind,
            indices,
            _fingerprint(
                {
                    "version": "2",
                    "result": fingerprint,
                    "policy": policy,
                    "destination": destination,
                    "kind": kind,
                    "indices": indices,
                }
            ),
        )
        for indices, kind in sorted(groups.items())
    )
