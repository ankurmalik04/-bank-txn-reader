"""Import policy and destination configuration, including bounded JSON loading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from bankparser.errors import InputError

Action = Literal["ignore", "review", "block"]
ACTIONS = frozenset({"ignore", "review", "block"})
FORMATS = frozenset({"csv", "mt940", "camt053", "ofx"})


@dataclass(frozen=True, slots=True)
class ImportPolicy:
    """Missing-field and review actions; none can override a failed invariant."""

    id: str = "default"
    version: str = "1"
    booking_date: Action = "block"
    value_date: Action = "ignore"
    transaction_currency: Action = "block"
    account_identity: Action = "review"
    description: Action = "ignore"
    reference: Action = "ignore"
    opening_balance: Action = "ignore"
    closing_balance: Action = "ignore"
    statement_period: Action = "ignore"
    duplicate_candidates: Action = "review"
    configured_currency: Action = "review"
    value_date_outside_period: Action = "review"
    other_incomplete_checks: Action = "review"
    other_warnings: Action = "review"
    empty_activity: Action = "review"
    allow_destination_account: bool = True
    value_date_exempt_formats: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("id", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InputError("Import policy id/version must be nonblank text")
        for field in fields(self):
            if field.name not in {
                "id",
                "version",
                "allow_destination_account",
                "value_date_exempt_formats",
            }:
                value = getattr(self, field.name)
                if not isinstance(value, str) or value not in ACTIONS:
                    raise InputError(
                        f"Import policy {field.name} must be ignore, review or block"
                    )
        if type(self.allow_destination_account) is not bool:
            raise InputError("allow_destination_account must be boolean")
        if (
            not isinstance(self.value_date_exempt_formats, tuple)
            or any(
                not isinstance(v, str) or v not in FORMATS
                for v in self.value_date_exempt_formats
            )
            or len(set(self.value_date_exempt_formats))
            != len(self.value_date_exempt_formats)
        ):
            raise InputError(
                "value_date_exempt_formats must be a tuple of unique supported formats"
            )


def load_import_policy(path: str | PathLike[str]) -> ImportPolicy:
    """Read a data-only v1 policy, bounded to 64 KiB, without executing code."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise InputError("Duplicate JSON key in import policy")
            value[key] = item
        return value

    def constant(value: str) -> Any:
        raise InputError("Nonfinite JSON number in import policy")

    try:
        with Path(path).open("rb") as source:
            data = source.read(65537)
        if len(data) > 65536:
            raise InputError("Import policy exceeds 64 KiB")
        document = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant
        )
        if not isinstance(document, dict) or set(document) != {
            "policy_schema_version",
            "policy",
        }:
            raise InputError("Import policy has missing or unknown fields")
        if document["policy_schema_version"] != "1" or not isinstance(
            document["policy"], dict
        ):
            raise InputError("Unsupported import policy schema or policy object")
        options = document["policy"]
        if "value_date_exempt_formats" in options:
            if not isinstance(options["value_date_exempt_formats"], list):
                raise InputError("JSON value_date_exempt_formats must be an array")
            options["value_date_exempt_formats"] = tuple(
                options["value_date_exempt_formats"]
            )
        return ImportPolicy(**options)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise InputError("Cannot load valid UTF-8 import policy/options") from exc


@dataclass(frozen=True, slots=True)
class DestinationAccount:
    """Caller-declared ledger destination, never inserted into source account data."""

    id: str
    currency: str | None = None
    source_account_id: str | None = None
    source_iban: str | None = None
    mapping_confirmed: bool = False

    def __post_init__(self) -> None:
        for name in ("id", "source_account_id", "source_iban"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise InputError("Destination identifiers must be nonblank text")
        if not isinstance(self.id, str):
            raise InputError("Destination account id is required")
        if self.currency is not None:
            if (
                not isinstance(self.currency, str)
                or re.fullmatch(r"[A-Za-z]{3}", self.currency) is None
            ):
                raise InputError("Destination currency must be three ASCII letters")
            object.__setattr__(self, "currency", self.currency.upper())
        if type(self.mapping_confirmed) is not bool:
            raise InputError("Destination mapping_confirmed must be boolean")
