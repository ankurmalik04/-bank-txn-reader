"""Public BankParser API."""

from .api import implementations, parse
from .comparison import ComparisonReport, compare
from .diagnostics import Diagnostic, diagnostic_for_error, diagnostics_for
from .errors import BankParserError, InputError, ParseError
from .models import ParseResult
from .options import CsvOptions
from .profiles import CsvProfile, load_csv_profile
from .readiness import (
    DestinationAccount,
    DuplicateCandidate,
    ImportAssessment,
    ImportPolicy,
    ImportReason,
    assess_import,
    load_import_policy,
)
from .version import __version__

__all__ = [
    "BankParserError",
    "ComparisonReport",
    "CsvOptions",
    "CsvProfile",
    "DestinationAccount",
    "Diagnostic",
    "DuplicateCandidate",
    "ImportAssessment",
    "ImportPolicy",
    "ImportReason",
    "InputError",
    "ParseError",
    "ParseResult",
    "__version__",
    "assess_import",
    "compare",
    "diagnostic_for_error",
    "diagnostics_for",
    "implementations",
    "load_csv_profile",
    "load_import_policy",
    "parse",
]
