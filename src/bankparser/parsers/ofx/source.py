"""Bounded OFX bank/card source checks, independent of backend repair logic.

This is a supported-profile validator, not an OFX schema implementation. SGML
leaves may omit end tags; aggregates must have matching explicit end tags.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from bankparser.errors import ParseError
from bankparser.models import Account, Statement, Transaction, Warning
from bankparser.parsers.base import CanonicalData
from bankparser.parsers.ofx.encoding import _decode_ofx
from bankparser.parsers.scalars import validate_amount_text

MAX_DEPTH = 64
_TAG = re.compile(r"</?([A-Za-z][A-Za-z0-9_.]*)\s*>")
_AGGREGATES = frozenset(
    [
        "OFX",
        "SIGNONMSGSRSV1",
        "SONRS",
        "FI",
        "STATUS",
        "BANKMSGSRSV1",
        "STMTTRNRS",
        "STMTRS",
        "CREDITCARDMSGSRSV1",
        "CCSTMTTRNRS",
        "CCSTMTRS",
        "BANKACCTFROM",
        "CCACCTFROM",
        "BANKTRANLIST",
        "STMTTRN",
        "LEDGERBAL",
        "AVAILBAL",
        "STMTTRNP",
        "BANKTRANLISTP",
        "CURRENCY",
        "ORIGCURRENCY",
        "PAYEE",
        "BANKACCTTO",
        "CCACCTTO",
        "INVSTMTRS",
        "LOANSTMTRS",
    ]
)
_SCALARS = frozenset(
    [
        "TRNAMT",
        "BALAMT",
        "CURDEF",
        "ACCTID",
        "BANKID",
        "ACCTTYPE",
        "DTSTART",
        "DTEND",
        "DTASOF",
        "DTPOSTED",
        "DTUSER",
        "DTAVAIL",
        "FITID",
        "NAME",
        "MEMO",
        "TRNTYPE",
        "CODE",
        "SEVERITY",
        "MESSAGE",
    ]
)
_DATE = re.compile(
    r"([0-9]{8})(?:([0-9]{6})(?:\.[0-9]+)?)?"
    r"(?:\[([+-]?[0-9]+(?:\.[0-9]+)?)(?::[^\[\]\s]+)?\])?"
)
_UNSUPPORTED = {
    "CORRECTFITID": "UNSUPPORTED_CORRECTION",
    "CORRECTACTION": "UNSUPPORTED_CORRECTION",
    "STMTTRNP": "UNSUPPORTED_PENDING_ACTIVITY",
    "BANKTRANLISTP": "UNSUPPORTED_PENDING_ACTIVITY",
    "CURRENCY": "UNSUPPORTED_TRANSACTION_CURRENCY",
    "ORIGCURRENCY": "UNSUPPORTED_TRANSACTION_CURRENCY",
    "INVSTMTRS": "UNSUPPORTED_OFX_SCOPE",
    "LOANSTMTRS": "UNSUPPORTED_OFX_SCOPE",
    "INVTRANLIST": "UNSUPPORTED_OFX_SCOPE",
    "LOANTRANLIST": "UNSUPPORTED_OFX_SCOPE",
}


@dataclass(frozen=True)
class OfxSource:
    backend_input: bytes
    canonical: CanonicalData


def _invalid(message: str, location: str = "OFX") -> ParseError:
    return ParseError(message, code="INVALID_OFX_STRUCTURE", location=location)


def _sgml(body: str) -> ET.Element:
    # Explicitly closed unknown elements are also bounded by the stack. Known
    # aggregates remain aggregates even if their end tag is missing.
    aggregates = _AGGREGATES | {
        match[1].upper() for match in _TAG.finditer(body) if match[0].startswith("</")
    }
    stack: list[ET.Element] = []
    root: ET.Element | None = None
    position = 0
    implicit_leaf = False
    for match in _TAG.finditer(body):
        content = body[position : match.start()]
        if "<" in content or ">" in content:
            raise _invalid("Unsupported SGML markup; use escaped text")
        if content.strip():
            if not stack or stack[-1].tag in _AGGREGATES or len(stack[-1]):
                raise _invalid("Unexpected text outside an OFX leaf")
            stack[-1].text = (stack[-1].text or "") + content
        tag = match[1].upper()
        closing = match[0].startswith("</")
        if implicit_leaf:
            if closing and stack[-1].tag == tag:
                raise _invalid("Ambiguous SGML leaf closure")
            stack.pop()
            implicit_leaf = False
        if closing:
            if not stack or stack[-1].tag != tag:
                raise _invalid(f"Mismatched SGML end tag {tag}")
            stack.pop()
        else:
            if len(stack) >= MAX_DEPTH or any(node.tag == tag for node in stack):
                raise _invalid("Excessive depth or nested repeated OFX aggregate")
            node = ET.Element(tag)
            if stack:
                if stack[-1].text and stack[-1].text.strip():
                    raise _invalid("OFX element mixes text and children")
                stack[-1].append(node)
            elif root is None:
                root = node
            else:
                raise _invalid("Multiple OFX document roots")
            stack.append(node)
            implicit_leaf = tag not in aggregates
        position = match.end()
    if body[position:].strip() or stack or root is None:
        raise _invalid("Truncated SGML document")
    # Decode only XML's five predefined/numeric entities, using hardened XML.
    # Bare ampersands in legacy SGML are literal; ambiguous entities are rejected.
    for node in root.iter():
        if node.text and "&" in node.text:
            node.text = _sgml_text(node.text)
    return root


def _sgml_text(value: str) -> str:
    if re.search(
        r"&(?!(?:amp|lt|gt|apos|quot|#[0-9]+|#x[0-9a-fA-F]+);)[^\s&]*;", value
    ):
        raise _invalid("Unsupported SGML entity")
    escaped = re.sub(
        r"&(?!(?:amp|lt|gt|apos|quot|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", value
    )
    try:
        return ET.fromstring(f"<TEXT>{escaped}</TEXT>").text or ""
    except ET.ParseError as exc:
        raise _invalid("Invalid SGML character reference") from exc


def _tree(data: bytes) -> ET.Element:
    text = _decode_ofx(data).lstrip("\ufeff \t\r\n")
    sgml_header = re.match(r"OFXHEADER:100\s", text, re.IGNORECASE)
    if sgml_header:
        start = re.search(r"<OFX\s*>", text, re.IGNORECASE)
        if start is None:
            raise _invalid("Missing OFX root")
        header = text[: start.start()]
        headers: dict[str, str] = {}
        for line in header.splitlines():
            if not line.strip():
                continue
            key, separator, value = line.partition(":")
            key = key.strip().upper()
            if not separator or key in headers:
                raise _invalid("Malformed or duplicate OFX header")
            headers[key] = value.strip().upper()
        if (
            headers.get("DATA") != "OFXSGML"
            or headers.get("VERSION") not in {"102", "103", "160"}
            or headers.get("SECURITY", "NONE") != "NONE"
            or headers.get("COMPRESSION", "NONE") != "NONE"
        ):
            raise ParseError(
                "Unsupported OFX SGML header",
                code="UNSUPPORTED_OFX_PROFILE",
                location="OFX header",
            )
        root = _sgml(text[start.start() :])
    else:
        # Parsing Unicode avoids stale byte-encoding declarations after decoding.
        safe_xml = importlib.import_module("defusedxml.ElementTree")
        exceptions = importlib.import_module("defusedxml.common")
        try:
            root = safe_xml.fromstring(
                text, forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
        except (ET.ParseError, exceptions.DefusedXmlException) as exc:
            raise _invalid("Malformed or unsafe OFX XML") from exc
    pending = [(root, 1)]
    while pending:
        node, depth = pending.pop()
        if (
            depth > MAX_DEPTH
            or not isinstance(node.tag, str)
            or _TAG.fullmatch(f"<{node.tag}>") is None
        ):
            raise _invalid("Unsupported OFX tag or excessive depth")
        node.tag = node.tag.upper()
        if node.tag in _SCALARS and len(node):
            raise _invalid("Expected a scalar OFX field", node.tag)
        if (
            node.attrib
            or (node.tail and node.tail.strip())
            or (len(node) and node.text and node.text.strip())
        ):
            raise _invalid("Attributes and mixed content are unsupported", node.tag)
        pending.extend((child, depth + 1) for child in node)
    if root.tag != "OFX":
        raise _invalid("Expected OFX root")
    return root


def _one(parent: ET.Element, tag: str, *, required: bool = False) -> ET.Element | None:
    nodes = parent.findall(tag)
    if len(nodes) > 1 or (required and not nodes):
        raise _invalid(
            f"Expected {'one' if required else 'at most one'} {tag}",
            f"{parent.tag}/{tag}",
        )
    return nodes[0] if nodes else None


def _value(
    parent: ET.Element, tag: str, *, required: bool = False, allow_empty: bool = False
) -> str | None:
    node = _one(parent, tag, required=required)
    if node is None:
        return None
    if len(node):
        raise _invalid("Expected a scalar field", f"{parent.tag}/{tag}")
    value = (node.text or "").strip() or None
    if value is None and not allow_empty:
        raise _invalid("Empty OFX field", f"{parent.tag}/{tag}")
    return value


def _day(value: str | None, location: str) -> date | None:
    if value is None:
        return None
    match = _DATE.fullmatch(value)
    try:
        if match is None:
            raise ValueError("Unsupported date syntax")
        if match[3] is not None and abs(Decimal(match[3])) > 24:
            raise ValueError("Invalid timezone offset")
        # Validate the reported civil date/time; canonical dates retain its day.
        instant = datetime.strptime(match[1] + (match[2] or "000000"), "%Y%m%d%H%M%S")
        return instant.date()
    except ValueError as exc:
        raise ParseError(
            "Invalid OFX date", code="INVALID_DATE", location=location
        ) from exc


def read_source(data: bytes) -> OfxSource:
    """Validate source semantics and retain exact monetary/date evidence."""
    root = _tree(data)
    warnings: list[Warning] = []
    for node in root:
        if node.tag.endswith("MSGSRSV1") and node.tag not in {
            "BANKMSGSRSV1",
            "CREDITCARDMSGSRSV1",
            "SIGNONMSGSRSV1",
        }:
            raise ParseError(
                "Unsupported OFX message family",
                code="UNSUPPORTED_OFX_SCOPE",
                location=node.tag,
            )
    for node in root.iter():
        if node.tag in _UNSUPPORTED:
            raise ParseError(
                f"Unsupported OFX activity: {node.tag}",
                code=_UNSUPPORTED[node.tag],
                location=node.tag,
            )
        if node.tag in {"TRNAMT", "BALAMT"}:
            if len(node):
                raise _invalid("Amount must be scalar", node.tag)
            validate_amount_text(node.text, location=f"OFX/{node.tag}")
        if node.tag == "STATUS":
            code = _value(node, "CODE", required=True)
            severity = _value(node, "SEVERITY", required=True)
            if code != "0" or severity not in {"INFO", "WARN"}:
                raise ParseError(
                    "OFX response reported an error",
                    code="OFX_RESPONSE_ERROR",
                    location="STATUS",
                )
            if severity == "WARN":
                warnings.append(
                    Warning(
                        "OFX_RESPONSE_WARNING",
                        "OFX response reported a warning",
                        "STATUS",
                    )
                )
    scopes = [node for node in root.iter() if node.tag in {"STMTRS", "CCSTMTRS"}]
    if len(scopes) != 1:
        raise ParseError(
            "Expected exactly one OFX bank/card statement",
            code="MULTIPLE_STATEMENTS",
            location="OFX/STMTRS or CCSTMTRS",
        )
    scope = scopes[0]
    account_tag = "BANKACCTFROM" if scope.tag == "STMTRS" else "CCACCTFROM"
    account = _one(scope, account_tag, required=True)
    assert account is not None
    account_id = _value(account, "ACCTID")
    currency = _value(scope, "CURDEF")
    if currency is not None:
        currency = currency.upper()
        if re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ParseError(
                "Invalid OFX currency", code="INVALID_CURRENCY", location="CURDEF"
            )
    activity = _one(scope, "BANKTRANLIST", required=True)
    assert activity is not None
    nodes = activity.findall("STMTTRN")
    if (
        len(list(root.iter("STMTTRN"))) != len(nodes)
        or len(list(root.iter("BANKTRANLIST"))) != 1
    ):
        raise _invalid("Transaction activity outside supported statement scope")
    if len(list(root.iter("TRNAMT"))) != len(nodes):
        raise _invalid("Transaction amount outside supported activity", "TRNAMT")
    for tag in ("BANKACCTFROM", "CCACCTFROM", "LEDGERBAL", "AVAILBAL"):
        if len(list(root.iter(tag))) != len(scope.findall(tag)):
            raise _invalid("Financial metadata outside supported statement scope", tag)
    other_account = "CCACCTFROM" if account_tag == "BANKACCTFROM" else "BANKACCTFROM"
    if _one(scope, other_account) is not None:
        raise _invalid("Conflicting account scope")
    transactions: list[Transaction] = []
    identities: set[str] = set()
    for index, node in enumerate(nodes, 1):
        location = f"{scope.tag}/BANKTRANLIST/STMTTRN[{index}]"
        amount_text = _value(node, "TRNAMT", required=True)
        validate_amount_text(amount_text, location=f"{location}/TRNAMT")
        assert amount_text is not None
        identity = _value(node, "FITID", required=True)
        assert identity is not None
        if identity in identities:
            raise ParseError(
                "Duplicate OFX FITID",
                code="DUPLICATE_TRANSACTION_ID",
                location=f"{location}/FITID",
            )
        identities.add(identity)
        posted = _value(node, "DTPOSTED", required=True)
        tags = [child.tag for child in node]
        if len(tags) != len(set(tags)):
            raise _invalid("Duplicate OFX transaction field", location)
        fields = {
            child.tag: (child.text or "").strip() for child in node if not len(child)
        }
        for tag in ("DTUSER", "DTAVAIL"):
            _day(_value(node, tag), f"{location}/{tag}")
        transactions.append(
            Transaction(
                booking_date=_day(posted, f"{location}/DTPOSTED"),
                value_date=None,
                amount=Decimal(amount_text),
                currency=currency,
                description=_value(node, "MEMO", allow_empty=True)
                or _value(node, "NAME", allow_empty=True),
                transaction_id=identity,
                raw={
                    "transaction_type": _value(node, "TRNTYPE"),
                    "source_fields": fields,
                    "source_path": location,
                },
            )
        )
    ledger = _one(scope, "LEDGERBAL")
    closing: Decimal | None = None
    closing_date: date | None = None
    if ledger is not None:
        closing_text = _value(ledger, "BALAMT", required=True)
        assert closing_text is not None
        closing = Decimal(closing_text)
        closing_date = _day(_value(ledger, "DTASOF", required=True), "LEDGERBAL/DTASOF")
    # Available balance is not a ledger balance, but still validate its evidence.
    available = _one(scope, "AVAILBAL")
    if available is not None:
        _value(available, "BALAMT", required=True)
        _day(_value(available, "DTASOF", required=True), "AVAILBAL/DTASOF")
    if len(list(root.iter("BALAMT"))) != int(ledger is not None) + int(
        available is not None
    ):
        raise _invalid("Balance amount outside supported balances", "BALAMT")
    if currency is None:
        warnings.append(
            Warning("MISSING_CURRENCY", "Statement currency is unavailable")
        )
    warnings.append(
        Warning("MISSING_OPENING_BALANCE", "Opening balance is unavailable")
    )
    if closing is None:
        warnings.append(
            Warning("MISSING_CLOSING_BALANCE", "Closing balance is unavailable")
        )
    canonical = CanonicalData(
        account=Account(id=account_id, currency=currency),
        statement=Statement(
            start_date=_day(_value(activity, "DTSTART"), "BANKTRANLIST/DTSTART"),
            end_date=_day(_value(activity, "DTEND"), "BANKTRANLIST/DTEND")
            or closing_date,
            closing_balance=closing,
            closing_balance_currency=currency if closing is not None else None,
        ),
        transactions=tuple(transactions),
        warnings=tuple(warnings),
    )
    # Empty optional text is absent metadata. ofxparse rejects empty NAME tags.
    for node in nodes:
        for tag in ("NAME", "MEMO"):
            child = node.find(tag)
            if child is not None and not (child.text or "").strip():
                node.remove(child)
    normalized = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    header = "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:UTF-8\nCHARSET:NONE\n\n"
    return OfxSource((header + normalized).encode("utf-8"), canonical)
