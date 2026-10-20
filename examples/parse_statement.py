"""Run from an installed checkout: python examples/parse_statement.py FILE."""

from __future__ import annotations

import json
import sys

from bankparser import BankParserError, parse
from bankparser.serialization import to_primitive


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python examples/parse_statement.py FILE", file=sys.stderr)
        return 2
    try:
        result = parse(sys.argv[1])
    except BankParserError as exc:
        print(f"{exc.code}: {exc} (location: {exc.location})", file=sys.stderr)
        return 2
    print(json.dumps(to_primitive(result), indent=2))
    return 0 if result.validation.status == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
