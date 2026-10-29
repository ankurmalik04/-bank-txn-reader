"""Public BankParser API."""

from .api import implementations, parse
from .comparison import ComparisonReport, compare
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
    "implementations",
    "load_csv_profile",
    "load_import_policy",
    "parse",
]
