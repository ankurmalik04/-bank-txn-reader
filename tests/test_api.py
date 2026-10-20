from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bankparser import api
from bankparser.errors import InputError, UnsupportedFormatError
from bankparser.models import Account, Statement, Transaction
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.registry import ParserRegistry


class FakeAdapter:
    id = "fake"
    format = "mt940"
    implementation_version = "1.0"

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        assert context.file_name == "basic_valid.mt940"
        return CanonicalData(
            account=Account(id="SYNTH-ACCOUNT", currency="GBP"),
            statement=Statement(
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 3),
                opening_balance=Decimal("1000.00"),
                closing_balance=Decimal("1174.50"),
            ),
            transactions=(
                Transaction(
                    date(2026, 10, 2),
                    date(2026, 10, 2),
                    Decimal("-25.50"),
                    "GBP",
                ),
                Transaction(
                    date(2026, 10, 3),
                    date(2026, 10, 3),
                    Decimal("200.00"),
                    "GBP",
                ),
            ),
        )


def test_public_parse_pipeline(monkeypatch) -> None:
    registry = ParserRegistry()
    registry.register(
        format="mt940", implementation="fake", factory=FakeAdapter, default=True
    )
    monkeypatch.setattr(api, "_default_registry", lambda: registry)

    result = api.parse(Path("corpus/mt940/basic_valid.mt940"))

    assert result.source.format == "mt940"
    assert result.source.implementation == "fake"
    assert result.validation.status == "passed"
    assert len(result.transactions) == 2


def test_empty_bytes_are_rejected() -> None:
    with pytest.raises(InputError, match="empty"):
        api.parse(b"")


def test_oversized_bytes_are_rejected() -> None:
    data = b"x" * (api.MAX_INPUT_BYTES + 1)
    with pytest.raises(InputError, match="too large"):
        api.parse(data)


def test_missing_path_is_reported_as_input_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mt940"
    with pytest.raises(InputError, match="Unable to read input file"):
        api.parse(missing)


def test_unsupported_content_is_explicit() -> None:
    with pytest.raises(UnsupportedFormatError):
        api.parse(b"this is not a bank statement")


def test_file_growth_between_stat_and_read_remains_bounded(monkeypatch) -> None:
    from io import BytesIO
    from types import SimpleNamespace

    read_sizes = []

    class GrowingFile(BytesIO):
        def read(self, size=-1):
            read_sizes.append(size)
            return super().read(size)

    monkeypatch.setattr(Path, "stat", lambda path: SimpleNamespace(st_size=1))
    monkeypatch.setattr(
        Path, "open", lambda path, mode: GrowingFile(b"x" * (api.MAX_INPUT_BYTES + 100))
    )
    with pytest.raises(InputError, match="too large"):
        api.parse(Path("growing.csv"))
    assert read_sizes == [api.MAX_INPUT_BYTES + 1]
