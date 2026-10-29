"""Versioned data-only CSV profiles; loading never executes exporter code."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import Any

from bankparser.errors import InputError
from bankparser.options import CsvOptions


@dataclass(frozen=True, slots=True)
class CsvProfile:
    """A named CSV convention set; identifiers and hashes are not certification."""

    id: str
    version: str
    options: CsvOptions
    sha256: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(v, str) or not v.strip() for v in (self.id, self.version)
        ):
            raise InputError("CSV profile id/version must be nonblank text")
        if not isinstance(self.options, CsvOptions):
            raise InputError("CSV profile options must be CsvOptions")
        if self.sha256 is not None and (
            not isinstance(self.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise InputError("Invalid CSV profile digest")


def load_csv_profile(path: str | PathLike[str]) -> CsvProfile:
    """Read a bounded UTF-8 JSON v1 profile with duplicate/unknown-key checks."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise InputError("Duplicate JSON key in CSV profile")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise InputError("Nonfinite JSON number in CSV profile")

    try:
        with Path(path).open("rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise InputError("CSV profile exceeds 64 KiB")
        value = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant
        )
        if not isinstance(value, dict) or set(value) != {
            "profile_schema_version",
            "id",
            "version",
            "format",
            "options",
        }:
            raise InputError("CSV profile has missing or unknown fields")
        if value["profile_schema_version"] != "1" or value["format"] != "csv":
            raise InputError("Unsupported CSV profile schema or format")
        if not isinstance(value["options"], dict):
            raise InputError("CSV profile options must be an object")
        return CsvProfile(
            value["id"],
            value["version"],
            CsvOptions(**value["options"]),
            hashlib.sha256(data).hexdigest(),
        )
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise InputError("Cannot load valid UTF-8 CSV profile/options") from exc
