"""Deterministic parser selection."""

from bankparser.parsers.base import ParserAdapter
from bankparser.parsers.registry import ParserRegistry


def select_parser(
    registry: ParserRegistry,
    *,
    format: str,
    implementation: str | None,
) -> ParserAdapter:
    """Select the configured default or an explicit implementation."""
    return registry.create(format, implementation)
