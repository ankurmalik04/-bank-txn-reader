"""Compare canonical results produced by multiple parser implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, localcontext
from os import PathLike
from typing import Any

from bankparser.api import _load_input, parse
from bankparser.api import implementations as available_implementations
from bankparser.detection import detect_format
from bankparser.errors import ComparisonError
from bankparser.models import ParseResult
from bankparser.options import CsvOptions
from bankparser.serialization import to_primitive

_MISSING = object()


@dataclass(frozen=True, slots=True)
class ComparisonDifference:
    """One canonical difference, with explicit presence for each implementation.

    Absent paths have a None value and present=False. A sourced null has
    present=True. The empty default preserves two-argument construction by
    callers; reports produced here always populate every presence flag.
    """

    path: str
    values: dict[str, Any]
    present: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    """Factual comparison of parser outputs for one input statement."""

    format: str
    implementations: tuple[str, ...]
    matches: bool
    differences: tuple[ComparisonDifference, ...]


def compare(
    source: str | PathLike[str] | bytes,
    *,
    implementations: Sequence[str] | None = None,
    csv_options: CsvOptions | None = None,
) -> ComparisonReport:
    """Run parser implementations and compare their canonical output.

    Source provenance and parser-specific ``raw`` transaction fields are excluded
    from comparison. Monetary fields compare by numeric value; other fields
    compare exactly. Reported differences retain their serialized values. This
    function never chooses a winning implementation.
    """
    # Compare a single snapshot even if a path is replaced while backends run.
    data, _ = _load_input(source)
    format_name = detect_format(data)
    selected = tuple(
        dict.fromkeys(
            available_implementations(format_name)
            if implementations is None
            else implementations
        )
    )
    if len(selected) < 2:
        raise ComparisonError("At least two parser implementations are required")

    results: dict[str, ParseResult] = {}
    for implementation in selected:
        results[implementation] = parse(
            data, implementation=implementation, csv_options=csv_options
        )

    return compare_results(results)


def compare_results(results: Mapping[str, ParseResult]) -> ComparisonReport:
    """Compare already-parsed results; useful for tests and other tooling."""
    if len(results) < 2:
        raise ComparisonError("At least two parser results are required")

    formats = {result.source.format for result in results.values()}
    if len(formats) != 1:
        raise ComparisonError("Parser results must describe the same input format")

    flattened = {
        implementation: _flatten(_comparable(result))
        for implementation, result in results.items()
    }
    all_paths = sorted({path for values in flattened.values() for path in values})

    differences: list[ComparisonDifference] = []
    for path in all_paths:
        values = {
            implementation: flattened[implementation].get(path, _MISSING)
            for implementation in results
        }
        keys = {
            _comparison_key(
                path, value, balance_amount=_is_balance_amount(path, flattened[name])
            )
            for name, value in values.items()
        }
        if len(keys) > 1:
            differences.append(
                ComparisonDifference(
                    path=path,
                    values={
                        name: None if value is _MISSING else value
                        for name, value in values.items()
                    },
                    present={
                        name: value is not _MISSING for name, value in values.items()
                    },
                )
            )

    return ComparisonReport(
        format=next(iter(formats)),
        implementations=tuple(results),
        matches=not differences,
        differences=tuple(differences),
    )


def _comparable(result: ParseResult) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []
    for transaction in result.transactions:
        item = to_primitive(transaction)
        item.pop("raw", None)
        transactions.append(item)

    return {
        "schema_version": result.schema_version,
        "account": to_primitive(result.account),
        "statement": to_primitive(result.statement),
        "transactions": transactions,
        "validation": to_primitive(result.validation),
        "warnings": to_primitive(result.warnings),
    }


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        if not value:
            return {path or "$": {}}
        flattened: dict[str, Any] = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            flattened.update(_flatten(item, child))
        return flattened

    if isinstance(value, list):
        if not value:
            return {path or "$": []}
        flattened = {}
        for index, item in enumerate(value):
            child = f"{path}[{index}]" if path else f"[{index}]"
            flattened.update(_flatten(item, child))
        return flattened

    return {path or "$": value}


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _is_balance_amount(path: str, fields: dict[str, Any]) -> bool:
    if not path.startswith("validation.checks[") or not path.endswith(
        (".expected", ".actual")
    ):
        return False
    return fields.get(path.rsplit(".", 1)[0] + ".code") == "BALANCE_RECONCILIATION"


def _comparison_key(path: str, value: Any, *, balance_amount: bool) -> Any:
    monetary = (
        path in {"statement.opening_balance", "statement.closing_balance"}
        or (path.startswith("transactions[") and path.endswith(".amount"))
        or balance_amount
    )
    if monetary and isinstance(value, str):
        try:
            # Invalid custom check text must not set the caller's context flags.
            with localcontext():
                number = Decimal(value)
        except InvalidOperation:
            pass
        else:
            if number.is_finite():
                return number
    return _freeze(value)
