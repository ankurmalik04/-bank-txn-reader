"""Simple deterministic parser registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from bankparser.errors import UnknownImplementationError
from bankparser.parsers.base import ParserAdapter

AdapterFactory = Callable[[], ParserAdapter]


@dataclass(slots=True)
class ParserRegistry:
    """Maps a format and implementation id to an adapter factory."""

    _factories: dict[str, dict[str, AdapterFactory]] = field(default_factory=dict)
    _defaults: dict[str, str] = field(default_factory=dict)

    def register(
        self,
        *,
        format: str,
        implementation: str,
        factory: AdapterFactory,
        default: bool = False,
    ) -> None:
        implementations = self._factories.setdefault(format, {})
        implementations[implementation] = factory
        if default or format not in self._defaults:
            self._defaults[format] = implementation

    def create(self, format: str, implementation: str | None = None) -> ParserAdapter:
        selected = implementation or self._defaults.get(format)
        if selected is None or selected not in self._factories.get(format, {}):
            available = ", ".join(self.implementations(format)) or "none"
            raise UnknownImplementationError(
                f"Unknown implementation {selected!r} for {format}; available: {available}"
            )
        return self._factories[format][selected]()

    def implementations(self, format: str) -> tuple[str, ...]:
        return tuple(sorted(self._factories.get(format, {})))

    def default_implementation(self, format: str) -> str | None:
        return self._defaults.get(format)
