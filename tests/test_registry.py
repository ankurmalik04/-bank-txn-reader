from dataclasses import dataclass

import pytest

from bankparser.errors import UnknownImplementationError
from bankparser.models import Account, Statement
from bankparser.parsers.base import CanonicalData, ParseContext
from bankparser.parsers.registry import ParserRegistry


@dataclass
class FakeAdapter:
    id: str = "fake"
    format: str = "mt940"
    implementation_version: str | None = "1"

    def parse(self, data: bytes, context: ParseContext) -> CanonicalData:
        return CanonicalData(Account(), Statement(), ())


def test_registry_uses_deterministic_default() -> None:
    registry = ParserRegistry()
    registry.register(
        format="mt940", implementation="fake", factory=FakeAdapter, default=True
    )
    assert registry.create("mt940").id == "fake"
    assert registry.implementations("mt940") == ("fake",)
    assert registry.default_implementation("mt940") == "fake"


def test_unknown_implementation_is_explicit() -> None:
    registry = ParserRegistry()
    registry.register(
        format="mt940", implementation="fake", factory=FakeAdapter, default=True
    )
    with pytest.raises(UnknownImplementationError):
        registry.create("mt940", "missing")


def test_unknown_format_has_no_default() -> None:
    registry = ParserRegistry()
    assert registry.implementations("missing") == ()
    assert registry.default_implementation("missing") is None
    with pytest.raises(UnknownImplementationError, match="available: none"):
        registry.create("missing")
