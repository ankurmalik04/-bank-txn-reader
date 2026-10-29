"""BankParser exception hierarchy."""

from bankparser.version import __version__


def dependency_install_hint(extra: str | None = None) -> str:
    """Describe installation from a downloaded release or a source checkout."""
    suffix = f"[{extra}]" if extra else ""
    wheel = f"./bankparser_runtime-{__version__}-py3-none-any.whl{suffix}"
    return (
        "Download and verify the wheel from the GitHub release, then run: "
        f'python -m pip install "{wheel}". '
        f'From a source checkout, run: python -m pip install ".{suffix}". '
        "Check the release notes for artifact checksums and installation details."
    )


class BankParserError(Exception):
    """Base exception for BankParser failures."""

    code = "BANKPARSER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        location: str | None = None,
        format: str | None = None,
        record_index: int | None = None,
        canonical_field: str | None = None,
        guidance: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or type(self).code
        self.location = location
        self.format = format
        self.record_index = record_index
        self.canonical_field = canonical_field
        self.guidance = guidance

    @property
    def severity(self) -> str:
        return "error"


class InputError(BankParserError):
    """Raised when the input cannot be safely loaded."""

    code = "INPUT_ERROR"


class UnsupportedFormatError(BankParserError):
    """Raised when BankParser cannot identify a supported format."""

    code = "UNSUPPORTED_FORMAT"


class UnknownImplementationError(BankParserError):
    """Raised when a parser implementation is not registered."""

    code = "UNKNOWN_IMPLEMENTATION"


class ParserDependencyError(BankParserError):
    """Raised when an adapter's underlying parser dependency is unavailable."""

    code = "MISSING_DEPENDENCY"


class ParseError(BankParserError):
    """Raised when an underlying parser cannot parse the supplied statement."""

    code = "PARSE_ERROR"


class ComparisonError(BankParserError):
    """Raised when parser outputs cannot be meaningfully compared."""

    code = "COMPARISON_ERROR"
