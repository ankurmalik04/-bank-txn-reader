"""Assess an independently invented corpus sample; no import is performed."""

import json
from pathlib import Path

from bankparser import assess_import, load_import_policy, parse
from bankparser.serialization import to_primitive

root = Path(__file__).resolve().parents[2]
policy = load_import_policy(root / "examples/import-readiness/movements.policy.json")
parsed = parse(root / "corpus/csv/basic_valid.csv")
print(json.dumps(to_primitive(assess_import(parsed, policy)), indent=2, sort_keys=True))
