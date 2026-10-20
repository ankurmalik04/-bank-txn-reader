"""Bank statement format detection."""

from bankparser.errors import UnsupportedFormatError

from .camt053 import looks_like_camt053
from .csv import looks_like_csv
from .mt940 import looks_like_mt940
from .ofx import looks_like_ofx


def detect_format(data: bytes) -> str:
    """Detect a supported bank statement format from file contents."""
    if looks_like_camt053(data):
        return "camt053"
    if looks_like_ofx(data):
        return "ofx"
    if looks_like_mt940(data):
        return "mt940"
    if looks_like_csv(data):
        return "csv"
    raise UnsupportedFormatError("Input is not a supported bank statement format")


__all__ = [
    "detect_format",
    "looks_like_camt053",
    "looks_like_csv",
    "looks_like_mt940",
    "looks_like_ofx",
]
