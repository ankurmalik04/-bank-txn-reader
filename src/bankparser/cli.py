"""Command line interface for BankParser."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from bankparser.api import implementations, parse
from bankparser.comparison import compare
from bankparser.errors import BankParserError, InputError
from bankparser.options import CsvOptions
from bankparser.profiles import load_csv_profile
from bankparser.readiness import DestinationAccount, assess_import, load_import_policy
from bankparser.serialization import to_primitive
from bankparser.version import __version__

_COMMANDS = {"parse", "compare", "assess", "implementations"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bankparser")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_parser = subparsers.add_parser("parse", help="parse a bank statement")
    parse_parser.add_argument("file")
    parse_parser.add_argument("--implementation", help="explicit parser implementation")
    parse_parser.add_argument(
        "--strict-validation",
        action="store_true",
        help="exit 3 unless every validation check passes",
    )
    _add_csv_options(parse_parser)
    parse_parser.add_argument(
        "--json-errors", action="store_true", help="emit structured errors on stderr"
    )

    compare_parser = subparsers.add_parser(
        "compare", help="compare canonical output from parser implementations"
    )
    compare_parser.add_argument("file")
    compare_parser.add_argument(
        "--implementation",
        action="append",
        dest="implementations",
        help="implementation to include; repeat to compare an explicit set",
    )
    _add_csv_options(compare_parser)
    compare_parser.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit 4 if the completed comparison reports differences",
    )
    compare_parser.add_argument(
        "--json-errors", action="store_true", help="emit structured errors on stderr"
    )

    assess_parser = subparsers.add_parser(
        "assess", help="assess parsed data against destination import policy"
    )
    assess_parser.add_argument("file")
    assess_parser.add_argument("--implementation")
    _add_csv_options(assess_parser)
    assess_parser.add_argument(
        "--policy", metavar="FILE", help="data-only version-1 import policy JSON"
    )
    assess_parser.add_argument(
        "--destination-account", help="destination ledger id, not a source identity"
    )
    assess_parser.add_argument("--destination-currency")
    assess_parser.add_argument("--expected-source-account")
    assess_parser.add_argument("--expected-source-iban")
    assess_parser.add_argument("--confirm-account-mapping", action="store_true")
    assess_parser.add_argument(
        "--reviewed-duplicate", action="append", metavar="FINGERPRINT"
    )
    assess_parser.add_argument("--json-errors", action="store_true")

    impl = subparsers.add_parser("implementations", help="list parser implementations")
    impl.add_argument("format")
    return parser


def _add_csv_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--decimal-separator", choices=(".", ","), help="explicit CSV decimal separator"
    )
    parser.add_argument("--grouping-separator", help="explicit CSV thousands separator")
    parser.add_argument(
        "--date-format", help="explicit CSV strptime date format, e.g. %%d/%%m/%%Y"
    )

    parser.add_argument(
        "--map",
        action="append",
        dest="column_mappings",
        metavar="SOURCE=FIELD",
        help="explicit source-header to canonical field mapping; replaces synonyms",
    )
    parser.add_argument("--date-role", choices=("booking_date", "value_date"))
    parser.add_argument("--default-currency", help="fill only missing source currency")
    parser.add_argument(
        "--expected-currency", help="require the effective currency to match"
    )
    parser.add_argument(
        "--header-row", type=int, help="physical start line of the header (1-based)"
    )
    parser.add_argument(
        "--header-search-limit",
        type=int,
        help="search first N physical lines (at most 200)",
    )
    parser.add_argument("--encoding", help="explicit UTF-8, cp1252 or Latin-1 encoding")
    parser.add_argument("--delimiter", choices=(",", ";", "\t", "|"))
    parser.add_argument(
        "--format", choices=("csv",), help="guarded CSV format override"
    )
    parser.add_argument(
        "--csv-profile", metavar="FILE", help="version-1 data-only CSV profile JSON"
    )


def _options_from_args(args: argparse.Namespace) -> CsvOptions | None:
    values: dict[str, Any] = {
        name: getattr(args, name)
        for name in (
            "decimal_separator",
            "grouping_separator",
            "date_format",
            "date_role",
            "default_currency",
            "expected_currency",
            "header_row",
            "header_search_limit",
            "encoding",
            "delimiter",
        )
        if getattr(args, name) is not None
    }
    if args.column_mappings is not None:
        mapping = {}
        for entry in args.column_mappings:
            source, separator, target = entry.rpartition("=")
            if not separator or not source or source in mapping:
                raise InputError("--map requires unique SOURCE=FIELD entries")
            mapping[source] = target
        values["columns"] = mapping
    if args.csv_profile and values:
        raise InputError("--csv-profile cannot be combined with CSV option overrides")
    return CsvOptions(**values) if values else None


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(_normalize_argv(raw_args))
    try:
        if args.command == "implementations":
            for implementation in implementations(args.format):
                print(implementation)
            return 0
        csv_options = _options_from_args(args)
        extra: dict[str, Any] = {}
        if args.csv_profile:
            extra["csv_profile"] = load_csv_profile(args.csv_profile)
        if args.format is not None:
            extra["format"] = args.format
        if args.command == "compare":
            report = compare(
                args.file,
                implementations=args.implementations,
                csv_options=csv_options,
                **extra,
            )
            print(json.dumps(to_primitive(report), indent=2, sort_keys=True))
            return 4 if args.fail_on_diff and not report.matches else 0
        policy = None
        destination = None
        if args.command == "assess":
            policy = load_import_policy(args.policy) if args.policy else None
            if args.destination_account is not None:
                destination = DestinationAccount(
                    args.destination_account,
                    args.destination_currency,
                    args.expected_source_account,
                    args.expected_source_iban,
                    args.confirm_account_mapping,
                )
            elif any(
                (
                    args.destination_currency,
                    args.expected_source_account,
                    args.expected_source_iban,
                    args.confirm_account_mapping,
                )
            ):
                raise InputError("Destination context requires --destination-account")
        result = parse(
            args.file,
            implementation=args.implementation,
            csv_options=csv_options,
            **extra,
        )
        if args.command == "assess":
            assessment = assess_import(
                result,
                policy,
                destination=destination,
                reviewed_duplicates=tuple(args.reviewed_duplicate or ()),
            )
            print(json.dumps(to_primitive(assessment), indent=2, sort_keys=True))
            return {"ready": 0, "review": 5, "not-ready": 6}[assessment.status]
        print(json.dumps(to_primitive(result), indent=2, sort_keys=True))
        if result.validation.status == "failed" or (
            args.strict_validation and result.validation.status != "passed"
        ):
            return 3
        return 0
    except BankParserError as exc:
        if getattr(args, "json_errors", False):
            print(
                json.dumps(
                    {
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                            "location": exc.location,
                        }
                    }
                ),
                file=sys.stderr,
            )
        else:
            location = f" ({exc.location})" if exc.location else ""
            print(f"bankparser: {exc.code}: {exc}{location}", file=sys.stderr)
        return 2


def _normalize_argv(argv: list[str]) -> list[str]:
    """Keep the original ``bankparser FILE`` shorthand alongside subcommands."""
    if (
        argv
        and argv[0] not in _COMMANDS
        and argv[0] not in {"-h", "--help", "--version"}
    ):
        return ["parse", *argv]
    return argv


if __name__ == "__main__":
    raise SystemExit(main())
