"""Conservative content-based CAMT.053 detection."""

from __future__ import annotations

import re

_NAMESPACE_PATTERN = re.compile(
    rb"urn:iso:std:iso:20022:tech:xsd:camt\.053\.\d{3}\.\d{2}",
    re.IGNORECASE,
)
_MESSAGE_PATTERN = re.compile(
    rb"<(?:[A-Za-z_][\w.-]*:)?BkToCstmrStmt(?:\s|>)",
    re.IGNORECASE,
)
_STATEMENT_PATTERN = re.compile(
    rb"<(?:[A-Za-z_][\w.-]*:)?Stmt(?:\s|>)",
    re.IGNORECASE,
)


def looks_like_camt053(data: bytes) -> bool:
    """Return True when content has a convincing CAMT.053 XML structure."""
    return bool(
        _NAMESPACE_PATTERN.search(data)
        and _MESSAGE_PATTERN.search(data)
        and _STATEMENT_PATTERN.search(data)
    )
