"""Declaration-aware decoding shared by OFX adapters."""

from __future__ import annotations

import codecs
import re

from bankparser.errors import ParseError


def _decode_ofx(data: bytes) -> str:
    """Honor OFX SGML charset headers and XML encoding declarations."""
    header = data[:2048].decode("ascii", errors="ignore")
    declaration = re.search(
        r"<\?xml[^>]*encoding=[\"\']([^\"\']+)", header, re.IGNORECASE
    )
    charset = re.search(r"(?im)^CHARSET:\s*([^\r\n]+)", header)
    encoding = re.search(r"(?im)^ENCODING:\s*([^\r\n]+)", header)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        selected = "utf-16"
    elif declaration:
        selected = declaration[1]
    elif charset and charset[1].strip().upper() not in {"NONE", "UNICODE"}:
        value = charset[1].strip()
        selected = (
            "iso-8859-1"
            if value == "8859-1"
            else (f"cp{value}" if value.isdigit() else value)
        )
    elif encoding and encoding[1].strip().upper() == "USASCII":
        selected = "ascii"
    else:
        selected = "utf-8-sig"
    try:
        codec = codecs.lookup(selected)
        if codec.name not in {
            "utf-8",
            "utf-8-sig",
            "ascii",
            "cp1252",
            "iso8859-1",
            "utf-16",
        }:
            raise LookupError(selected)
        return data.decode(selected)
    except (LookupError, UnicodeDecodeError) as exc:
        raise ParseError(
            f"Unsupported or invalid OFX encoding {selected!r}; export UTF-8 or Windows-1252",
            code="INVALID_ENCODING",
            location="OFX encoding declaration",
        ) from exc
