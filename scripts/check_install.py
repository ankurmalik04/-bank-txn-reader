"""Verify a clean installed release profile. Run with its Python and -I."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_core(value):
    return {
        "account": value["account"],
        "statement": value["statement"],
        "transactions": [
            {k: v for k, v in item.items() if k != "raw"}
            for item in value["transactions"]
        ],
        "validation_status": value["validation"]["status"],
        "validation_checks": [
            {k: c[k] for k in ("code", "status", "expected", "actual")}
            for c in value["validation"]["checks"]
        ],
        "warning_codes": sorted(w["code"] for w in value["warnings"]),
    }


def check(profile, corpus):
    import bankparser
    from bankparser import BankParserError, parse
    from bankparser.serialization import to_primitive

    require(sys.flags.isolated, "Run with Python -I to exclude checkout/PYTHONPATH")
    require(sys.prefix != sys.base_prefix, "Use a dedicated virtual environment")
    require(
        Path(bankparser.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()),
        "BankParser was imported from outside the virtual environment",
    )
    dist = metadata.distribution("bankparser-runtime")
    require(
        (Path(bankparser.__file__).parent / "py.typed").is_file(), "Missing type marker"
    )
    require(
        not any(importlib.util.find_spec(n) for n in ("pytest", "pip_audit", "build")),
        "Runtime environment contains development/audit tools",
    )
    absent = ()
    if profile in ("base", "csv", "ofx"):
        absent += ("bankstatementparser", "pandas", "numpy", "pydantic")
    if profile in ("base", "csv"):
        absent += ("ofxparse", "bs4", "lxml", "defusedxml")
    if profile in ("camt", "alternative"):
        absent += ("ofxparse", "bs4")
    require(
        not any(importlib.util.find_spec(n) for n in absent),
        f"Unexpected optional dependency in {profile} install",
    )
    require(
        not any(
            n in sys.modules
            for n in ("pandas", "numpy", "bankstatementparser", "ofxparse", "lxml")
        ),
        "Importing BankParser eagerly loaded an optional backend",
    )
    cases = [("mt940/basic_valid.mt940", "wolph"), ("csv/basic_valid.csv", "native")]
    if profile in ("ofx", "all"):
        cases += [("ofx/basic_valid.ofx", "ofxparse")]
    if profile in ("camt", "alternative", "all"):
        cases += [("camt053/basic_valid.camt053.xml", "bankstatementparser")]
    if profile in ("alternative", "all"):
        cases += [
            ("mt940/basic_valid.mt940", "bankstatementparser"),
            ("csv/all_fields.csv", "bankstatementparser"),
            ("ofx/basic_valid.ofx", "bankstatementparser"),
        ]
    executable = Path(sys.executable).parent / (
        "bankparser.exe" if sys.platform == "win32" else "bankparser"
    )
    require(executable.is_file(), "Installed CLI entry point missing")
    with tempfile.TemporaryDirectory(prefix="bankparser-smoke-") as cwd:
        version = subprocess.check_output(
            [str(executable), "--version"], cwd=cwd, text=True
        ).strip()
        require(
            version == f"bankparser {dist.version}", "CLI/package versions disagree"
        )
        for relative, implementation in cases:
            path = corpus / relative
            expected_path = path.with_name(path.name.split(".")[0] + ".expected.json")
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            result = parse(path, implementation=implementation)
            require(
                result.source.implementation == implementation, "Unexpected backend"
            )
            if implementation != "bankstatementparser":
                require(
                    parse(path).source.implementation == implementation,
                    "Installing an extra changed the default implementation",
                )
            require(
                canonical_core(to_primitive(result)) == expected,
                f"API golden mismatch: {relative}",
            )
            cli = json.loads(
                subprocess.check_output(
                    [
                        str(executable),
                        "parse",
                        str(path),
                        "--implementation",
                        implementation,
                    ],
                    cwd=cwd,
                    text=True,
                )
            )
            require(canonical_core(cli) == expected, f"CLI golden mismatch: {relative}")
        missing = (
            ["camt053/basic_valid.camt053.xml"]
            if profile in ("base", "csv", "ofx")
            else []
        )
        if profile not in ("ofx", "all"):
            missing += ["ofx/basic_valid.ofx"]
        for relative in missing:
            try:
                parse(corpus / relative)
            except BankParserError as error:
                require(
                    error.code == "MISSING_DEPENDENCY", "Wrong missing-backend error"
                )
                require(
                    "GitHub release" in str(error) and ".whl[" in str(error),
                    "Missing backend lacks GitHub-download installation guidance",
                )
            else:
                raise ValueError("Missing backend did not raise a dependency error")
            failed_cli = subprocess.run(
                [str(executable), "parse", str(corpus / relative), "--json-errors"],
                cwd=cwd, text=True, capture_output=True, check=False,
            )
            require(failed_cli.returncode == 2, "Wrong missing-backend CLI exit status")
            require(not failed_cli.stdout, "Missing-backend CLI wrote to stdout")
            error = json.loads(failed_cli.stderr)["error"]
            require(error["code"] == "MISSING_DEPENDENCY", "Wrong CLI error code")
            require("GitHub release" in error["message"], "CLI lacks installation guidance")
    require(
        not any(n in sys.modules for n in absent), "Excluded dependency was imported"
    )
    print(
        f"Verified {profile}: installed API/CLI, {len(cases)} independent goldens, optional isolation"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("base", "csv", "ofx", "camt", "alternative", "all"), required=True
    )
    parser.add_argument("--corpus", type=Path, required=True)
    args = parser.parse_args()
    check(args.profile, args.corpus.resolve())
