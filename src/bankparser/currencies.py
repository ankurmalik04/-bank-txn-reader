"""Currency syntax shared by source readers and canonical validation."""

import re


def is_currency_code(value: str) -> bool:
    """Check three ASCII letters; this does not certify an assigned ISO code."""
    return re.fullmatch(r"[A-Za-z]{3}", value) is not None
