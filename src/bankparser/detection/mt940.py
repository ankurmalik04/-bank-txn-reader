"""Conservative content-based MT940 detection."""

from __future__ import annotations

import re

_TAG_PATTERN = re.compile(rb"(?m)^(?:\xef\xbb\xbf)?:(20|25|28C|60[FM]|61|62[FM]):")


def looks_like_mt940(data: bytes) -> bool:
    """Return True when content has a convincing MT940 tag combination."""
    tags = {match.group(1) for match in _TAG_PATTERN.finditer(data)}
    has_identity = b"20" in tags and b"25" in tags
    has_transaction = b"61" in tags
    has_statement_structure = any(
        tag in tags for tag in (b"28C", b"60F", b"60M", b"62F", b"62M")
    )
    has_balances = any(tag in tags for tag in (b"60F", b"60M")) and any(
        tag in tags for tag in (b"62F", b"62M")
    )
    return (
        has_identity and has_statement_structure and (has_transaction or has_balances)
    )
