"""Compare frozen, independently authored expectations with one-profile samples.

Reports contain financial data. Keep private inputs, expectations and reports
outside public Git. This tool neither authors expectations nor certifies banks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import sys
from datetime import date, datetime, timezone
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, localcontext
from pathlib import Path

from bankparser import BankParserError, CsvOptions, parse
from bankparser.api import MAX_INPUT_BYTES, SCHEMA_VERSION
from bankparser.serialization import to_primitive
from bankparser.version import __version__

VERSION = "1"
LIMIT = MAX_INPUT_BYTES
ACCOUNT = {"id", "iban", "currency"}
STATEMENT = {
    "id",
    "sequence",
    "start_date",
    "end_date",
    "opening_balance",
    "closing_balance",
    "opening_balance_currency",
    "closing_balance_currency",
}
TRANSACTION = {
    "booking_date",
    "value_date",
    "amount",
    "currency",
    "description",
    "counterparty",
    "reference",
    "transaction_id",
}
COUNTERPARTY = {"name", "account_id", "iban"}
FORMATS = {"csv", "mt940", "camt053", "ofx"}
DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ConformanceInputError(ValueError):
    """Invalid configuration, expectations or inaccessible bounded input."""


def require(condition, message):
    if not condition:
        raise ConformanceInputError(message)


def fields(value, required, optional=(), *, at):
    require(isinstance(value, dict), f"{at}: expected an object")
    require(
        required <= value.keys() <= required | set(optional),
        f"{at}: missing or unknown fields",
    )


def text(value, at, *, nullable=False):
    require(
        (nullable and value is None)
        or (isinstance(value, str) and bool(value.strip())),
        f"{at}: expected nonblank text" + (" or null" if nullable else ""),
    )


def read_bytes(path, *, at):
    try:
        with path.open("rb") as stream:
            data = stream.read(LIMIT + 1)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ConformanceInputError(f"{at}: cannot read file") from exc
    require(len(data) <= LIMIT, f"{at}: exceeds {LIMIT} bytes")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(data, *, at):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"{at}: duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ConformanceInputError(f"{at}: nonfinite JSON number")

    def floating(value):
        number = float(value)
        require(math.isfinite(number), f"{at}: nonfinite JSON number")
        return number

    try:
        value = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=pairs,
            parse_constant=constant,
            parse_float=floating,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ConformanceInputError):
            raise
        raise ConformanceInputError(f"{at}: invalid UTF-8 JSON") from exc
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        require(depth <= 64, f"{at}: JSON nesting exceeds 64 levels")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return value


def amount(value, at, *, nullable=False):
    require(
        (nullable and value is None)
        or (isinstance(value, str) and DECIMAL.fullmatch(value) is not None),
        f"{at}: expected a plain exact decimal string"
        + (" or null" if nullable else ""),
    )


def validate_record(record, keys, *, at):
    fields(record, keys, at=at)
    for key, value in record.items():
        path = at + "." + key
        if key in {"amount", "opening_balance", "closing_balance"}:
            amount(value, path, nullable=key != "amount")
        elif key in {"booking_date", "value_date", "start_date", "end_date"}:
            if value is not None:
                require(isinstance(value, str), f"{path}: expected ISO date or null")
                try:
                    parsed = date.fromisoformat(value)
                except ValueError as exc:
                    raise ConformanceInputError(f"{path}: invalid ISO date") from exc
                require(parsed.isoformat() == value, f"{path}: expected YYYY-MM-DD")
        elif key == "counterparty":
            validate_record(value, COUNTERPARTY, at=path)
        else:
            require(
                value is None or isinstance(value, str),
                f"{path}: expected text or null",
            )


def validate_expectation(value):
    fields(
        value,
        {
            "expectation_schema_version",
            "canonical_schema_version",
            "account",
            "statement",
            "transactions",
        },
        at="expectation",
    )
    require(
        value["expectation_schema_version"] == VERSION,
        "unsupported expectation schema version",
    )
    require(
        value["canonical_schema_version"] == SCHEMA_VERSION,
        "unsupported canonical schema version",
    )
    validate_record(value["account"], ACCOUNT, at="account")
    validate_record(value["statement"], STATEMENT, at="statement")
    require(isinstance(value["transactions"], list), "transactions: expected an array")
    for index, record in enumerate(value["transactions"]):
        validate_record(record, TRANSACTION, at=f"transactions[{index}]")
    return {key: value[key] for key in ("account", "statement", "transactions")}


def validate_manifest(value):
    fields(value, {"manifest_schema_version", "profile", "samples"}, at="manifest")
    require(
        value["manifest_schema_version"] == VERSION,
        "unsupported manifest schema version",
    )
    profile = value["profile"]
    fields(
        profile,
        {
            "id",
            "version",
            "exporter",
            "format",
            "format_version",
            "settings",
            "implementation",
            "csv_options",
        },
        at="profile",
    )
    for key in ("id", "version", "exporter", "format_version", "implementation"):
        text(profile[key], f"profile.{key}")
    require(
        isinstance(profile["format"], str) and profile["format"] in FORMATS,
        "profile.format: unsupported format",
    )
    fields(
        profile["settings"],
        {
            "encoding",
            "account_type",
            "currency",
            "locale",
            "date_convention",
            "amount_convention",
        },
        {"extra"},
        at="profile.settings",
    )
    for key in profile["settings"]:
        if key == "extra":
            require(
                isinstance(profile["settings"][key], dict),
                "profile.settings.extra: expected object",
            )
        else:
            text(
                profile["settings"][key],
                f"profile.settings.{key}",
                nullable=key == "currency",
            )
    options = profile["csv_options"]
    require(
        options is None or profile["format"] == "csv",
        "csv_options require a CSV profile",
    )
    if options is not None:
        fields(
            options,
            set(),
            set(CsvOptions.__dataclass_fields__),
            at="csv_options",
        )
        try:
            CsvOptions(**options)
        except BankParserError as exc:
            raise ConformanceInputError("invalid csv_options") from exc
    require(
        isinstance(value["samples"], list) and 0 < len(value["samples"]) <= 1000,
        "samples: expected 1 to 1000 samples",
    )
    ids = set()
    for sample in value["samples"]:
        fields(
            sample,
            {
                "id",
                "source",
                "source_sha256",
                "expected",
                "expected_sha256",
                "evidence",
                "policy_differences",
            },
            at="sample",
        )
        for key in ("id", "source", "expected"):
            text(sample[key], f"sample.{key}")
        require(sample["id"] not in ids, "duplicate sample id")
        ids.add(sample["id"])
        for key in ("source_sha256", "expected_sha256"):
            require(
                isinstance(sample[key], str)
                and SHA256.fullmatch(sample[key]) is not None,
                f"sample.{key}: expected lowercase SHA-256",
            )
        evidence = sample["evidence"]
        fields(
            evidence,
            {
                "kind",
                "cohort",
                "permission",
                "expectation_author",
                "expectation_method",
                "independent_reviewer",
                "held_out_untouched",
            },
            at="evidence",
        )
        require(
            isinstance(evidence["kind"], str)
            and evidence["kind"] in {"synthetic", "demo", "production"},
            "evidence.kind: expected synthetic, demo or production",
        )
        require(
            isinstance(evidence["cohort"], str)
            and evidence["cohort"] in {"development", "held-out"},
            "evidence.cohort: expected development or held-out",
        )
        for key in (
            "permission",
            "expectation_author",
            "expectation_method",
            "independent_reviewer",
        ):
            text(
                evidence[key], f"evidence.{key}", nullable=key == "independent_reviewer"
            )
        require(
            evidence["independent_reviewer"] != evidence["expectation_author"],
            "independent reviewer must differ from expectation author",
        )
        require(
            type(evidence["held_out_untouched"]) is bool,
            "held_out_untouched: expected boolean",
        )
        require(
            not evidence["held_out_untouched"] or evidence["cohort"] == "held-out",
            "untouched evidence must belong to held-out cohort",
        )
        policies = sample["policy_differences"]
        require(isinstance(policies, list), "policy_differences: expected an array")
        paths = set()
        for policy in policies:
            fields(policy, {"path", "reason"}, at="policy difference")
            text(policy["path"], "policy.path")
            text(policy["reason"], "policy.reason")
            require(policy["path"] not in paths, "duplicate policy difference path")
            paths.add(policy["path"])
    return value


def flatten(value, path=""):
    # Keep empty containers and array lengths; repeats and order are significant.
    if isinstance(value, dict):
        if not value:
            return {path: {}}
        return {
            p: v
            for key, item in value.items()
            for p, v in flatten(item, f"{path}.{key}" if path else key).items()
        }
    if isinstance(value, list):
        result = {path + ".length": len(value)}
        for index, item in enumerate(value):
            result.update(flatten(item, f"{path}[{index}]"))
        return result
    return {path: value}


def financial(path):
    return (
        path.startswith(("account.", "statement."))
        or path == "transactions.length"
        or (
            path.startswith("transactions[")
            and path.rsplit(".", 1)[-1]
            in {"amount", "currency", "booking_date", "value_date", "transaction_id"}
        )
    )


def monetary(path):
    return path.endswith((".amount", ".opening_balance", ".closing_balance"))


def differences(wanted, actual, policies):
    expected_fields, actual_fields = flatten(wanted), flatten(actual)
    allowed = {p["path"]: p["reason"] for p in policies}
    for path in allowed:
        require(
            path in expected_fields and not financial(path),
            "policy differences must identify a known metadata leaf",
        )
    result = []
    for path in sorted(expected_fields.keys() | actual_fields.keys()):
        expected_present, actual_present = (
            path in expected_fields,
            path in actual_fields,
        )
        left, right = expected_fields.get(path), actual_fields.get(path)
        equal = expected_present == actual_present and left == right
        if (
            expected_present
            and actual_present
            and monetary(path)
            and left is not None
            and right is not None
        ):
            equal = Decimal(left) == Decimal(right)
        if not equal:
            result.append(
                {
                    "path": path,
                    "category": "policy"
                    if path in allowed
                    else ("financial" if financial(path) else "metadata"),
                    "expected_present": expected_present,
                    "actual_present": actual_present,
                    "expected": left,
                    "actual": right,
                    "policy_reason": allowed.get(path),
                }
            )
    return result


def totals(transactions):
    result = {}
    for transaction in transactions:
        currency = transaction["currency"]
        result[currency] = result.get(currency, Decimal(0)) + Decimal(
            transaction["amount"]
        )
    return result


def total_rows(values):
    return [
        {"currency": currency, "amount": format(values[currency], "f")}
        for currency in sorted(values, key=lambda v: (v is not None, v or ""))
    ]


def check(code, status, reason):
    return {"code": code, "status": status, "reason": reason}


def balance_check(core, code):
    statement = core["statement"]
    opening, closing = statement["opening_balance"], statement["closing_balance"]
    currency = statement["opening_balance_currency"]
    if (
        opening is None
        or closing is None
        or currency is None
        or currency != statement["closing_balance_currency"]
    ):
        return check(
            code, "skipped", "Missing balances or incompatible balance currencies"
        )
    if any(t["currency"] != currency for t in core["transactions"]):
        return check(code, "skipped", "Unknown or incompatible transaction currencies")
    movement = totals(core["transactions"]).get(currency, Decimal(0))
    passed = Decimal(opening) + movement == Decimal(closing)
    return check(
        code,
        "passed" if passed else "failed",
        "Opening plus booked movements versus closing",
    )


def run_sample(sample, profile, base):
    evidence = sample["evidence"]
    row = {
        "id": sample["id"],
        "status": "error",
        "evidence": evidence,
        "source_sha256": None,
        "expected_sha256": None,
        "backend": None,
        "counts": None,
        "booked_totals": None,
        "fields_checked": 0,
        "alignment": "ordinal; no identity rematching or deduplication",
        "differences": [],
        "checks": [],
        "parser_validation": None,
        "warning_codes": [],
        "error": None,
    }
    checks = row["checks"]
    checks.extend(
        [
            check(
                "PRODUCTION_EVIDENCE",
                "passed" if evidence["kind"] == "production" else "skipped",
                "Declared sample kind; synthetic/demo evidence is not production coverage",
            ),
            check(
                "INDEPENDENT_REVIEW",
                "passed" if evidence["independent_reviewer"] else "skipped",
                "Declared independent second review; not authenticated by this runner",
            ),
            check(
                "HELD_OUT_EVIDENCE",
                "passed"
                if evidence["cohort"] == "held-out" and evidence["held_out_untouched"]
                else "skipped",
                "Declared untouched held-out use; development/tuned samples do not qualify",
            ),
        ]
    )
    try:
        data = read_bytes(base / sample["source"], at="source")
        frozen = read_bytes(base / sample["expected"], at="expectation")
        row["source_sha256"], row["expected_sha256"] = digest(data), digest(frozen)
        for key in ("source_sha256", "expected_sha256"):
            same = row[key] == sample[key]
            checks.append(
                check(
                    key.upper(),
                    "passed" if same else "failed",
                    "Frozen bytes match manifest digest",
                )
            )
            require(same, key + ": frozen bytes changed")
        wanted = validate_expectation(load_json(frozen, at="expectation"))
        # Validate exception paths before invoking any parser.
        differences(wanted, wanted, sample["policy_differences"])
        options = profile["csv_options"]
        result = parse(
            data,
            implementation=profile["implementation"],
            csv_options=CsvOptions(**options) if options is not None else None,
        )
        row["backend"] = {
            key: value
            for key, value in to_primitive(result.source).items()
            if key != "file_name"
        }
        require(
            result.source.format == profile["format"],
            "detected format does not match profile",
        )
        require(
            result.schema_version == SCHEMA_VERSION, "parser canonical schema changed"
        )
        actual = {
            "account": to_primitive(result.account),
            "statement": to_primitive(result.statement),
            "transactions": [
                {key: value for key, value in to_primitive(t).items() if key != "raw"}
                for t in result.transactions
            ],
        }
        # Bound arithmetic by literal digits, independently of caller precision/traps.
        precision = max(28, len(frozen) + len(data))
        with localcontext(Context(prec=precision, Emin=MIN_EMIN, Emax=MAX_EMAX)):
            row["differences"] = differences(
                wanted, actual, sample["policy_differences"]
            )
            expected_totals, actual_totals = (
                totals(wanted["transactions"]),
                totals(actual["transactions"]),
            )
            row["booked_totals"] = {
                "expected": total_rows(expected_totals),
                "actual": total_rows(actual_totals),
            }
            checks.append(
                check(
                    "BOOKED_TOTALS",
                    "passed" if expected_totals == actual_totals else "failed",
                    "Compare exact signed totals separately by currency; null currency is not inferred",
                )
            )
            checks.extend(
                [
                    balance_check(wanted, "EXPECTED_BALANCE_CONSERVATION"),
                    balance_check(actual, "ACTUAL_BALANCE_CONSERVATION"),
                ]
            )
        expected_count, actual_count = (
            len(wanted["transactions"]),
            len(actual["transactions"]),
        )
        row["counts"] = {
            "expected": expected_count,
            "actual": actual_count,
            "missing_count": max(0, expected_count - actual_count),
            "extra_count": max(0, actual_count - expected_count),
        }
        checks.append(
            check(
                "TRANSACTION_COUNT",
                "passed" if expected_count == actual_count else "failed",
                "Count delta only; ordinal differences do not establish record identity",
            )
        )
        row["fields_checked"] = len(flatten(wanted))
        row["parser_validation"] = {
            "status": result.validation.status,
            "checks": [
                {"code": c.code, "status": c.status} for c in result.validation.checks
            ],
        }
        row["warning_codes"] = sorted(w.code for w in result.warnings)
        checks.append(
            check(
                "PARSER_VALIDATION",
                "failed"
                if result.validation.status == "failed"
                else ("passed" if result.validation.status == "passed" else "skipped"),
                "Parser's internal validation; skipped prerequisites remain explicit",
            )
        )
        failed = any(c["status"] == "failed" for c in checks) or any(
            d["category"] != "policy" for d in row["differences"]
        )
        row["status"] = "failed" if failed else "passed"
    except ConformanceInputError as exc:
        row["error"] = {
            "code": "CONFORMANCE_INPUT_ERROR",
            "location": None,
            "reason": str(exc),
        }
    except BankParserError as exc:
        # Avoid copying arbitrary backend exception messages or filenames into diagnostics.
        row["error"] = {
            "code": exc.code,
            "location": exc.location,
            "reason": "Parser failed; no partial result compared",
        }
    return row


def run(manifest_path):
    manifest_path = Path(manifest_path)
    data = read_bytes(manifest_path, at="manifest")
    manifest = validate_manifest(load_json(data, at="manifest"))
    rows = [
        run_sample(sample, manifest["profile"], manifest_path.parent)
        for sample in manifest["samples"]
    ]
    facts = {
        "manifest_sha256": digest(data),
        "profile": manifest["profile"],
        "canonical_schema_version": SCHEMA_VERSION,
        "samples": rows,
        "summary": {
            status: sum(r["status"] == status for r in rows)
            for status in ("passed", "failed", "error")
        },
        "certification": "not assessed; declared evidence and matching results do not certify a profile",
    }
    return {
        "report_schema_version": VERSION,
        "facts": facts,
        "execution": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "bankparser_version": __version__,
        },
    }


def markdown(report):
    def cell(value):
        return (
            json.dumps(value, ensure_ascii=True)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("\\n", "<br>")
        )

    facts = report["facts"]
    lines = [
        "# Conformance report",
        "",
        "Private financial data may appear below. No bank/profile certification is asserted.",
        "",
        f"Profile: {cell(facts['profile']['id'])}, version {cell(facts['profile']['version'])}",
        "",
        "| Sample | Status | Expected count | Actual count |",
        "| --- | --- | --- | --- |",
    ]
    for row in facts["samples"]:
        counts = row["counts"] or {"expected": None, "actual": None}
        lines.append(
            f"| {cell(row['id'])} | {row['status']} | {counts['expected']} | {counts['actual']} |"
        )
    for row in facts["samples"]:
        lines.extend(
            [
                "",
                f"## Sample {cell(row['id'])}",
                "",
                f"Evidence: {cell(row['evidence'])}",
                "",
                f"Source SHA-256: {cell(row['source_sha256'])}",
                "",
                f"Expectation SHA-256: {cell(row['expected_sha256'])}",
                "",
                f"Backend: {cell(row['backend'])}",
                "",
                f"Alignment: {row['alignment']}",
                "",
                f"Booked totals: {cell(row['booked_totals'])}",
                "",
                f"Parser validation: {cell(row['parser_validation'])}",
                "",
                f"Warning codes: {cell(row['warning_codes'])}",
                "",
                "| Check | Status | Reason |",
                "| --- | --- | --- |",
            ]
        )
        for c in row["checks"]:
            lines.append(f"| {c['code']} | {c['status']} | {cell(c['reason'])} |")
        if row["error"]:
            lines.extend(["", "Error: " + cell(row["error"])])
        lines.extend(
            [
                "",
                "| Field | Category | Expected present | Expected | Actual present | Actual | Policy reason |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for d in row["differences"]:
            lines.append(
                f"| {cell(d['path'])} | {d['category']} | {d['expected_present']} | {cell(d['expected'])} | "
                f"{d['actual_present']} | {cell(d['actual'])} | {cell(d['policy_reason'])} |"
            )
    lines.extend(["", "Execution: " + cell(report["execution"]), ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--json", type=Path, help="new JSON report file (default: stdout)"
    )
    parser.add_argument("--markdown", type=Path, help="new Markdown report file")
    args = parser.parse_args(argv)
    try:
        # Refuse existing outputs, including inputs; never overwrite frozen evidence.
        outputs = [p for p in (args.json, args.markdown) if p is not None]
        require(
            len({p.resolve() for p in outputs}) == len(outputs),
            "output paths must differ",
        )
        require(
            all(not p.exists() and not p.is_symlink() for p in outputs),
            "report output already exists",
        )
        report = run(args.manifest)
        encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        if args.json:
            with args.json.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        else:
            print(encoded, end="")
        if args.markdown:
            with args.markdown.open("x", encoding="utf-8") as stream:
                stream.write(markdown(report))
        summary = report["facts"]["summary"]
        return 2 if summary["error"] else (1 if summary["failed"] else 0)
    except (ConformanceInputError, OSError) as exc:
        message = (
            str(exc)
            if isinstance(exc, ConformanceInputError)
            else "cannot create report output"
        )
        print(
            json.dumps(
                {"error": {"code": "CONFORMANCE_INPUT_ERROR", "message": message}}
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
