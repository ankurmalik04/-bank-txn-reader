"""Conservative content-based OFX/QFX detection."""

from __future__ import annotations

import re

_ROOT_PATTERN = re.compile(rb"<\s*OFX\b", re.IGNORECASE)
_SCOPE_PATTERN = re.compile(rb"<\s*(?:STMTRS|CCSTMTRS)\b", re.IGNORECASE)
_STRUCTURE_PATTERN = re.compile(
    rb"<\s*(?:BANKTRANLIST|BANKACCTFROM|CCACCTFROM)\b", re.IGNORECASE
)


def looks_like_ofx(data: bytes) -> bool:
    """Return True for a convincing OFX/QFX document structure.

    QFX uses the OFX wire format, so both are intentionally reported as the
    ``ofx`` format family. Detection is based on content, not file extension.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            data = data.decode("utf-16").encode("utf-8")
        except UnicodeDecodeError:
            return False
    return bool(
        _ROOT_PATTERN.search(data)
        and _SCOPE_PATTERN.search(data)
        and _STRUCTURE_PATTERN.search(data)
    )
