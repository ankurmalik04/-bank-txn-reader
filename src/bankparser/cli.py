"""Command line interface for BankParser."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from bankparser.api import implementations, parse
from bankparser.comparison import compare
from bankparser.errors import BankParserError
from bankparser.options import CsvOptions
from bankparser.serialization import to_primitive
from bankparser.version import __version__

_COMMANDS = {"parse", "compare", "implementations"}


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


def main(argv: Sequence[str] | None = None) -> int:
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    args = build_parser().parse_args(_normalize_argv(raw_args))
    try:
        if args.command == "implementations":
            for implementation in implementations(args.format):
                print(implementation)
            return 0
        csv_options = None
        if any((args.decimal_separator, args.grouping_separator, args.date_format)):
            csv_options = CsvOptions(
                args.decimal_separator, args.grouping_separator, args.date_format
            )
        if args.command == "compare":
            report = compare(
                args.file, implementations=args.implementations, csv_options=csv_options
            )
            print(json.dumps(to_primitive(report), indent=2, sort_keys=True))
            return 4 if args.fail_on_diff and not report.matches else 0
        result = parse(
            args.file, implementation=args.implementation, csv_options=csv_options
        )
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
