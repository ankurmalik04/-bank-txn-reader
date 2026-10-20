"""OFX adversarial scenarios over the independently authored project corpus.

Expected projections are authored separately from production parser outputs.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def xml_document(sgml, encoding="UTF-8"):
    body = sgml[sgml.index("<OFX>") :]
    # Test-fixture builder: close leaf tags in our known synthetic SGML template.
    body = re.sub(r"<([A-Z0-9.]+)>([^<\r\n]+)(?=\n)", r"<\1>\2</\1>", body)
    return f'<?xml version="1.0" encoding="{encoding}"?>\n' + body


def cases():
    basic = (ROOT / "corpus/ofx/basic_valid.ofx").read_bytes()
    text = basic.decode("ascii")
    golden = json.loads((ROOT / "corpus/ofx/basic_valid.expected.json").read_text())
    rows = []

    def add(name, data, expected, rationale):
        rows.append(
            {"name": name, "data": data, "expected": expected, "rationale": rationale}
        )

    add(
        "corpus_bank_sgml",
        basic,
        {"full": golden},
        "Independent committed canonical fixture",
    )
    add(
        "corpus_windows1252",
        (ROOT / "corpus/ofx/windows1252.ofx").read_bytes(),
        {
            "full": json.loads(
                (ROOT / "corpus/ofx/windows1252.expected.json").read_text()
            )
        },
        "Independent committed non-ASCII fixture",
    )
    qfx_golden = json.loads(
        (ROOT / "corpus/ofx/basic_valid.qfx.expected.json").read_text()
    )
    add(
        "corpus_card_qfx",
        (ROOT / "corpus/ofx/basic_valid.qfx").read_bytes(),
        {"full": qfx_golden},
        "Authored full projection of the existing card fixture",
    )
    add(
        "corpus_multiple_scopes",
        (ROOT / "corpus/ofx/multiple_statements.ofx").read_bytes(),
        {"reject": True},
        "Keep our single-scope contract",
    )
    xml = xml_document(text)
    add("bank_xml", xml.encode(), {"full": golden}, "Same facts, closed XML leaf tags")
    add(
        "xml_unicode",
        xml.replace("Test materials", "Café € 東京").encode(),
        {"tx.0.description": "Café € 東京"},
        "Preserve UTF-8 XML descriptions",
    )
    add(
        "xml_utf16",
        xml_document(text, "UTF-16").encode("utf-16"),
        {"full": golden},
        "Proposed encoding case; current detection gap is already documented",
    )
    add(
        "sgml_utf8",
        text.replace("ENCODING:USASCII", "ENCODING:UTF-8")
        .replace("CHARSET:1252", "CHARSET:NONE")
        .replace("Test materials", "Café € 東京")
        .encode(),
        {"tx.0.description": "Café € 東京"},
        "Preserve declared UTF-8 SGML",
    )
    add(
        "xml_entities",
        xml.replace("Test materials", "Coffee &amp; cake &lt;3").encode(),
        {"tx.0.description": "Coffee & cake <3"},
        "Decode XML entities once",
    )
    add(
        "xml_truncated",
        xml.replace("</OFX>", "").encode(),
        {"reject": True},
        "Malformed XML must not be repaired silently",
    )
    add(
        "xml_internal_entity",
        xml.replace("<OFX>", '<!DOCTYPE OFX [<!ENTITY probe "EXPANDED">]><OFX>', 1)
        .replace("Test materials", "&probe;")
        .encode(),
        {"reject": True},
        "Proposed hardened XML boundary rejects declared entities",
    )
    add(
        "sgml_unclosed_transaction",
        basic.replace(b"</STMTTRN>", b"", 1),
        {"reject": True},
        "Missing aggregate closure risks merging records",
    )
    add(
        "unknown_encoding",
        basic.replace(b"CHARSET:1252", b"CHARSET:99999"),
        {"reject": True},
        "Unsupported encoding must fail",
    )
    add(
        "positive_timezone",
        basic.replace(b"20260915000000", b"20260915003000[+2:CET]", 1),
        {"tx.0.booking_date": "2026-09-15"},
        "Explicit proposed policy: retain reported local booking day",
    )
    add(
        "negative_timezone",
        basic.replace(b"20260915000000", b"20260915233000[-5:EST]", 1),
        {"tx.0.booking_date": "2026-09-15"},
        "Same proposed policy at the opposite day boundary",
    )
    add(
        "date_only",
        basic.replace(b"20260915000000", b"20260915", 1),
        {"tx.0.booking_date": "2026-09-15"},
        "Date-only posting",
    )
    add(
        "invalid_date",
        basic.replace(b"20260915000000", b"20261399000000", 1),
        {"reject": True},
        "Invalid financial date must fail",
    )
    add(
        "zero_date",
        basic.replace(b"20260915000000", b"00000000", 1),
        {"reject": True},
        "Missing posting date must not masquerade as a valid record",
    )
    for value in ("null", "NaN", "Infinity", "1E+2", "-25,50", ""):
        add(
            "amount_" + (value or "empty"),
            basic.replace(b"-18.75", value.encode(), 1),
            {"reject": True},
            "Plain finite decimal source amounts required",
        )
    add(
        "missing_amount",
        basic.replace(b"<TRNAMT>-18.75\n", b"", 1),
        {"reject": True},
        "Required financial amount cannot be absent",
    )
    exact = "-123456789012345678901234567890.123456789"
    add(
        "exact_large_amount",
        basic.replace(b"-18.75", exact.encode(), 1),
        {"tx.0.amount": exact},
        "Preserve coefficient and scale without float arithmetic",
    )
    add(
        "missing_fitid",
        basic.replace(b"<FITID>SYNTH-OFX-1\n", b"", 1),
        {"reject": True},
        "Proposed strict identity policy for a replacement",
    )
    add(
        "duplicate_fitid",
        basic.replace(b"SYNTH-OFX-2", b"SYNTH-OFX-1", 1),
        {"reject": True},
        "Proposed conflicting identity policy; do not silently deduplicate",
    )
    add(
        "missing_currency",
        basic.replace(b"<CURDEF>GBP\n", b"", 1),
        {"account.currency": None, "warnings_include": "MISSING_CURRENCY"},
        "Preserve absent currency",
    )
    add(
        "missing_ledger",
        re.sub(rb"<LEDGERBAL>.*?</LEDGERBAL>", b"", basic, flags=re.DOTALL),
        {
            "statement.closing_balance": None,
            "warnings_include": "MISSING_CLOSING_BALANCE",
        },
        "Preserve incomplete balance information",
    )
    add(
        "empty_activity",
        re.sub(rb"<STMTTRN>.*?</STMTTRN>", b"", basic, flags=re.DOTALL),
        {"transaction_count": 0, "statement.closing_balance": "561.25"},
        "Balance-only activity is valid",
    )
    for action in ("REPLACE", "DELETE"):
        add(
            "correction_" + action.lower(),
            basic.replace(
                b"<FITID>SYNTH-OFX-1\n",
                b"<FITID>SYNTH-OFX-1\n<CORRECTFITID>PRIOR-001\n<CORRECTACTION>"
                + action.encode()
                + b"\n",
                1,
            ),
            {"reject": True},
            "Unsupported correction directives need explicit handling",
        )
    add(
        "foreign_currency",
        basic.replace(
            b"<FITID>SYNTH-OFX-1\n",
            b"<FITID>SYNTH-OFX-1\n<CURRENCY><CURRATE>1.2\n<CURSYM>USD\n</CURRENCY>\n",
            1,
        ),
        {"reject": True},
        "Reject unsupported per-transaction currency rather than mislabel it",
    )
    add(
        "response_error",
        basic.replace(
            b"<TRNUID>0\n",
            b"<TRNUID>0\n<STATUS><CODE>2001\n"
            b"<SEVERITY>ERROR\n<MESSAGE>Invalid account\n</STATUS>\n",
            1,
        ),
        {"reject": True},
        "Error responses must not be successful statement imports",
    )
    add(
        "pending_activity",
        basic.replace(
            b"</BANKTRANLIST>",
            b"<STMTTRNP><TRNTYPE>DEBIT\n"
            b"<DTTRAN>20260916000000\n<TRNAMT>-10.00\n<NAME>Pending\n</STMTTRNP>\n</BANKTRANLIST>",
        ),
        {"reject": True},
        "Proposed boundary: report unsupported pending financial activity",
    )
    return rows


def check(actual, expected):
    if expected.get("reject"):
        # Programming errors in the experimental mapping are not valid rejection.
        return "error" in actual and actual["error"] not in {
            "AttributeError",
            "TypeError",
            "IndexError",
            "KeyError",
            "NameError",
            "UnboundLocalError",
            "ModuleNotFoundError",
            "ImportError",
        }
    if "error" in actual:
        return False
    if "full" in expected:
        return actual == expected["full"]
    for path, value in expected.items():
        if path == "transaction_count":
            observed = len(actual["transactions"])
        elif path == "warnings_include":
            if value not in actual["warning_codes"]:
                return False
            continue
        else:
            observed = actual
            for part in path.replace("tx.", "transactions.").split("."):
                observed = observed[int(part)] if part.isdigit() else observed[part]
        if observed != value:
            return False
    return True
