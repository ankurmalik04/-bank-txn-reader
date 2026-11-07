"""Third-party exception strings must not enter ordinary CLI diagnostics."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from bankparser import cli
from bankparser.errors import ParseError
from bankparser.parsers.base import ParseContext

PRIVATE = "PRIVATE-ACCOUNT-123 /private/customer.ofx sensitive narrative"


@pytest.mark.parametrize("backend", ["camt", "camt-extract", "csv", "ofx", "mt940", "wolph"])
def test_backend_error_is_sanitized_and_chained(backend, monkeypatch, capsys):
    failure = ValueError(PRIVATE)

    def broken(*args, **kwargs):
        raise failure

    class Broken:
        __init__ = broken
        from_bytes = staticmethod(broken)

    format = {"camt": "camt053", "camt-extract": "camt053", "wolph": "mt940"}.get(backend, backend)
    module = importlib.import_module(
        f"bankparser.parsers.{format}.{'wolph' if backend == 'wolph' else 'bankstatementparser'}"
    )
    name = {"camt053": "Camt053", "csv": "Csv", "ofx": "Ofx", "mt940": "Mt940"}[format]
    cls = getattr(module, "WolphMt940Adapter" if backend == "wolph" else f"BankStatementParser{name}Adapter")
    adapter = cls.__new__(cls)
    adapter._parser_class = Broken
    adapter._mt940 = SimpleNamespace(Options=lambda **kwargs: None, parse_statements=broken)
    suffix = {"camt053": "camt053.xml", "csv": "csv", "ofx": "ofx", "mt940": "mt940"}[format]
    path = Path(f"corpus/{format}/basic_valid.{suffix}")
    if backend == "camt-extract":
        root = ET.fromstring(path.read_bytes())
        for node in root.iter():
            node.tag = node.tag.rsplit("}", 1)[-1]
        adapter._parser_class = SimpleNamespace(
            from_bytes=lambda *args, **kwargs: SimpleNamespace(tree=root, get_transactions=broken)
        )
    with pytest.raises(ParseError) as caught:
        adapter.parse(path.read_bytes(), ParseContext())
    error = caught.value
    assert error.__cause__ is failure
    assert PRIVATE not in str(error)

    def parse_error(*args, **kwargs):
        raise error

    monkeypatch.setattr(cli, "parse", parse_error)
    for policy in ("full", "redacted-diagnostic"):
        for json_errors in (False, True):
            args = ["parse", str(path), "--output-policy", policy]
            if json_errors:
                args.append("--json-errors")
            assert cli.main(args) == 2
            assert "PRIVATE-ACCOUNT" not in capsys.readouterr().err


@pytest.mark.parametrize("format", ["camt053", "ofx", "mt940"])
def test_invalid_backend_scalar_does_not_echo_value(format):
    module = importlib.import_module(f"bankparser.parsers.{format}.bankstatementparser")
    with pytest.raises(ParseError) as caught:
        module._required_decimal(PRIVATE)
    assert PRIVATE not in str(caught.value)
