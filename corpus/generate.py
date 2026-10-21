"""Independently authored synthetic corpus, 2026-10-09 (project MIT license).

No statement samples, old corpus files, parsers or expected-output files are read.
The literals below define invented scenarios. Goldens describe their intended
canonical meaning, not the output of a production implementation.
Run `python corpus/generate.py` to write, or add `--check` to verify exact bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
D1, D2, D3 = "2026-09-14", "2026-09-15", "2026-09-16"


def iban(serial):
    """Construct a test label with a UK-shaped BBAN and mod-97 checksum."""
    bban = f"TEST000000{serial:08d}"
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in bban + "GB00")
    return f"GB{98 - int(digits) % 97:02d}{bban}"


ACCOUNT, OTHER = iban(1), iban(2)


def tx(
    amount,
    description,
    booking=None,
    value=None,
    reference=None,
    identity=None,
    name=None,
    counterparty=None,
    currency="GBP",
):
    return {
        "booking_date": booking,
        "value_date": value,
        "amount": amount,
        "currency": currency,
        "description": description,
        "reference": reference,
        "transaction_id": identity,
        "counterparty": {
            "name": name,
            "account_id": counterparty,
            "iban": counterparty,
        },
    }


def core(
    transactions,
    *,
    account=ACCOUNT,
    iban_value=None,
    currency="GBP",
    identity=None,
    sequence=None,
    start=D1,
    end=D3,
    opening=None,
    closing=None,
    closing_currency=None,
    balance_actual=None,
    balance_status=None,
    currency_status="passed",
    warnings=(),
):
    warnings = list(warnings)
    if opening is None:
        warnings.append("MISSING_OPENING_BALANCE")
    if closing is None:
        warnings.append("MISSING_CLOSING_BALANCE")
    status = balance_status or (
        "skipped" if opening is None or closing is None else "passed"
    )
    # The API names the declared closing balance "expected" and the
    # independently computed opening + movements "actual".
    expected = closing if status != "skipped" else None
    date_status = (
        "skipped"
        if start is None or end is None
        else ("passed" if start <= end else "failed")
    )
    identity_status = (
        "passed" if (account or "").strip() or (iban_value or "").strip() else "skipped"
    )
    if identity_status == "skipped":
        warnings.append("MISSING_ACCOUNT_IDENTITY")
    transaction_currency_status = (
        "passed"
        if all((t["currency"] or "").strip() for t in transactions)
        else "skipped"
    )

    def date_range_status(field, booking):
        if not transactions:
            return "passed"
        if start is not None and end is not None and start > end:
            return "skipped"
        dates = [t[field] for t in transactions]
        outside = any(
            d is not None
            and ((start is not None and d < start) or (end is not None and d > end))
            for d in dates
        )
        if outside:
            return "failed" if booking else "skipped"
        return "skipped" if start is None or end is None or None in dates else "passed"

    booking_status = date_range_status("booking_date", True)
    value_status = date_range_status("value_date", False)
    statuses = (
        status,
        currency_status,
        date_status,
        identity_status,
        transaction_currency_status,
        booking_status,
        value_status,
    )
    return {
        "account": {"id": account, "iban": iban_value, "currency": currency},
        "statement": {
            "id": identity,
            "sequence": sequence,
            "start_date": start,
            "end_date": end,
            "opening_balance": opening,
            "closing_balance": closing,
            "opening_balance_currency": currency if opening is not None else None,
            "closing_balance_currency": (closing_currency or currency)
            if closing is not None
            else None,
        },
        "transactions": transactions,
        "validation_status": "failed"
        if "failed" in statuses
        else ("warning" if "skipped" in statuses else "passed"),
        "warning_codes": sorted(warnings),
        "validation_checks": [
            {
                "code": "BALANCE_RECONCILIATION",
                "status": status,
                "expected": expected,
                "actual": (balance_actual or closing) if status != "skipped" else None,
            },
            {
                "code": "CURRENCY_CONSISTENCY",
                "status": currency_status,
                "expected": None,
                "actual": None,
            },
            {
                "code": "FINITE_AMOUNTS",
                "status": "passed",
                "expected": None,
                "actual": None,
            },
            {
                "code": "STATEMENT_DATE_ORDER",
                "status": date_status,
                "expected": f"start_date <= {end}"
                if date_status != "skipped"
                else None,
                "actual": start if date_status != "skipped" else None,
            },
            *[
                {"code": code, "status": check_status, "expected": None, "actual": None}
                for code, check_status in (
                    ("TRANSACTION_CURRENCIES", transaction_currency_status),
                    ("TRANSACTION_BOOKING_DATES", booking_status),
                    ("TRANSACTION_VALUE_DATES", value_status),
                )
            ],
            {
                "code": "ACCOUNT_IDENTITY",
                "status": identity_status,
                "expected": None,
                "actual": None,
            },
        ],
    }


def mt940(
    number,
    lines,
    opening="500,00",
    closing="561,25",
    end="260916",
    account=ACCOUNT,
    currency="GBP",
):
    rows = [f":20:SYNTH-MT-{number}", f":25:{account}", f":28C:{number}/1"]
    if opening is not None:
        rows.append(f":60F:C260914GBP{opening}")
    rows.extend(lines)
    if closing is not None:
        rows.append(f":62F:C{end}{currency}{closing}")
    return "\n".join(rows) + "\n"


def csv_text(headers, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(headers.split(","))
    writer.writerows(rows)
    return stream.getvalue()


def camt_statement(*, all_fields=False, identity="SYNTH-CAMT-1"):
    entries = []
    for i, (date, amount, direction, role, name, narrative) in enumerate(
        [
            (D2, "18.75", "DBIT", "Cdtr", "Synthetic Workshop", "Test materials"),
            (D3, "80.00", "CRDT", "Dbtr", "Synthetic Sponsor", "Test contribution"),
        ],
        1,
    ):
        instruction = (
            "<InstrId>SYNTH-INSTR-1</InstrId>" if all_fields and i == 1 else ""
        )
        cp = (
            f"<CdtrAcct><Id><IBAN>{OTHER}</IBAN></Id></CdtrAcct>"
            if all_fields and i == 1
            else ""
        )
        extra = (
            "<Ustrd>Test receipt 7</Ustrd><Strd><CdtrRefInf><Ref>SYNTH-RF-7</Ref></CdtrRefInf></Strd>"
            if all_fields and i == 1
            else ""
        )
        entries.append(f"""      <Ntry>
        <Amt Ccy="GBP">{amount}</Amt><CdtDbtInd>{direction}</CdtDbtInd>
        <Sts><Cd>BOOK</Cd></Sts>
        <BookgDt><Dt>{date}</Dt></BookgDt><ValDt><Dt>{date}</Dt></ValDt>
        <BkTxCd><Prtry><Cd>SYNTH</Cd></Prtry></BkTxCd>
        <NtryDtls><TxDtls>
          <Refs>{instruction}<AcctSvcrRef>SYNTH-BANK-{i}</AcctSvcrRef><EndToEndId>SYNTH-E2E-{i}</EndToEndId></Refs>
          <RltdPties><{role}><Nm>{name}</Nm></{role}>{cp}</RltdPties>
          <RmtInf><Ustrd>{narrative}</Ustrd>{extra}</RmtInf>
        </TxDtls></NtryDtls>
      </Ntry>""")
    return f"""    <Stmt>
      <Id>{identity}</Id><ElctrncSeqNb>1</ElctrncSeqNb><CreDtTm>{D3}T12:00:00Z</CreDtTm>
      <Acct><Id><IBAN>{ACCOUNT}</IBAN></Id><Ccy>GBP</Ccy></Acct>
      <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="GBP">500.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{D1}</Dt></Dt></Bal>
{chr(10).join(entries)}
      <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="GBP">561.25</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{D3}</Dt></Dt></Bal>
    </Stmt>"""


def camt_document(statements):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
  <BkToCstmrStmt><GrpHdr><MsgId>SYNTH-CAMT</MsgId><CreDtTm>{D3}T12:00:00Z</CreDtTm></GrpHdr>
{statements}
  </BkToCstmrStmt>
</Document>
"""


OFX_HEADER = "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\nCHARSET:1252\n\n"


def ofx_scope(*, card=False, memo="Test materials", account=ACCOUNT):
    scope, acct_tag = ("CCSTMTRS", "CCACCTFROM") if card else ("STMTRS", "BANKACCTFROM")
    currency, end, balance = (
        ("USD", "20260915", "-7.00") if card else ("GBP", "20260916", "561.25")
    )
    rows = [
        (
            "DEBIT",
            "20260915",
            "-7.00" if card else "-18.75",
            "SYNTH-QFX-1" if card else "SYNTH-OFX-1",
            "Synthetic Workshop",
            "Test card purchase" if card else memo,
        )
    ]
    if not card:
        rows.append(
            (
                "CREDIT",
                "20260916",
                "80.00",
                "SYNTH-OFX-2",
                "Synthetic Sponsor",
                "Test contribution",
            )
        )
    entries = "".join(
        f"<STMTTRN>\n<TRNTYPE>{kind}\n<DTPOSTED>{date}000000\n<TRNAMT>{amount}\n<FITID>{identity}\n<NAME>{name}\n<MEMO>{desc}\n</STMTTRN>\n"
        for kind, date, amount, identity, name, desc in rows
    )
    bank = "" if card else "<BANKID>TEST\n"
    acct_type = "" if card else "<ACCTTYPE>CHECKING\n"
    return f"<{scope}>\n<CURDEF>{currency}\n<{acct_tag}>\n{bank}<ACCTID>{account}\n{acct_type}</{acct_tag}>\n<BANKTRANLIST>\n<DTSTART>20260914000000\n<DTEND>{end}000000\n{entries}</BANKTRANLIST>\n<LEDGERBAL>\n<BALAMT>{balance}\n<DTASOF>{end}000000\n</LEDGERBAL>\n</{scope}>\n"


def ofx_document(scopes, *, card=False):
    group, response = (
        ("CREDITCARDMSGSRSV1", "CCSTMTTRNRS") if card else ("BANKMSGSRSV1", "STMTTRNRS")
    )
    return (
        OFX_HEADER
        + f"<OFX>\n<{group}>\n<{response}>\n<TRNUID>0\n{scopes}</{response}>\n</{group}>\n</OFX>\n"
    )


def artifacts():
    files = {}

    def add(path, source, expected=None, encoding="utf-8"):
        files[path] = source.encode(encoding)
        if expected is not None:
            # .camt053.xml and .qfx have distinct golden naming conventions.
            stem = (
                path.removesuffix(".camt053.xml")
                if path.endswith(".camt053.xml")
                else path.rsplit(".", 1)[0]
            )
            if path.endswith(".qfx"):
                stem += ".qfx"
            files[stem + ".expected.json"] = (
                json.dumps(expected, indent=2) + "\n"
            ).encode()

    basic_lines = [
        ":61:2609150915D18,75NTRFMATERIAL//SYNTH-BANK-1",
        ":86:Test materials",
        ":61:2609160916C80,00NTRFDONATION//SYNTH-BANK-2",
        ":86:Test contribution",
    ]
    mt_txs = [
        tx("-18.75", "Test materials", D2, D2, "MATERIAL"),
        tx("80.00", "Test contribution", D3, D3, "DONATION"),
    ]
    common = {
        "identity": "1",
        "sequence": "1",
        "opening": "500.00",
        "closing": "561.25",
    }
    add("mt940/basic_valid.mt940", mt940(1, basic_lines), core(mt_txs, **common))
    add(
        "mt940/balance_mismatch.mt940",
        mt940(2, basic_lines, closing="560,00"),
        core(
            mt_txs,
            identity="2",
            sequence="1",
            opening="500.00",
            closing="560.00",
            balance_actual="561.25",
            balance_status="failed",
        ),
    )
    add(
        "mt940/missing_description.mt940",
        mt940(
            3,
            [":61:260915D7,00NTRFNO-DESC//SYNTH-BANK-3"],
            opening="30,00",
            closing="23,00",
            end="260915",
        ),
        core(
            [tx("-7.00", None, value=D2, reference="NO-DESC")],
            identity="3",
            sequence="1",
            end=D2,
            opening="30.00",
            closing="23.00",
        ),
    )
    add(
        "mt940/reversals.mt940",
        mt940(
            4,
            [
                ":61:260915RC4,00NTRFREV-C//SYNTH-BANK-4",
                ":86:Test reversed credit",
                ":61:260916RD2,00NTRFREV-D//SYNTH-BANK-5",
                ":86:Test reversed debit",
            ],
            opening="30,00",
            closing="28,00",
        ),
        core(
            [
                tx("-4.00", "Test reversed credit", value=D2, reference="REV-C"),
                tx("2.00", "Test reversed debit", value=D3, reference="REV-D"),
            ],
            identity="4",
            sequence="1",
            opening="30.00",
            closing="28.00",
        ),
    )
    add(
        "mt940/missing_opening_balance.mt940",
        mt940(
            5,
            [
                ":61:260915C7,00NTRFCREDIT//SYNTH-BANK-6",
                ":86:Test credit without opening",
            ],
            opening=None,
            closing="37,00",
            end="260915",
        ),
        core(
            [tx("7.00", "Test credit without opening", value=D2, reference="CREDIT")],
            identity="5",
            sequence="1",
            start=D2,
            end=D2,
            closing="37.00",
        ),
    )
    add(
        "mt940/missing_closing_balance.mt940",
        mt940(
            6,
            [
                ":61:260915D7,00NTRFDEBIT//SYNTH-BANK-7",
                ":86:Test debit without closing",
            ],
            opening="30,00",
            closing=None,
        ),
        core(
            [tx("-7.00", "Test debit without closing", value=D2, reference="DEBIT")],
            identity="6",
            sequence="1",
            end=D2,
            opening="30.00",
        ),
    )
    add(
        "mt940/no_activity.mt940",
        mt940(1, [], closing="500,00"),
        core([], **(common | {"closing": "500.00"})),
    )
    add(
        "mt940/currency_conflict.mt940",
        mt940(1, basic_lines, currency="USD"),
        core(mt_txs, **common, closing_currency="USD", currency_status="failed"),
    )
    for name, account in [
        ("multiple_accounts", OTHER),
        ("multiple_statements", ACCOUNT),
    ]:
        add(
            f"mt940/{name}.mt940",
            mt940(1, basic_lines) + mt940(2, [], account=account, closing="500,00"),
            {"error": {"code": "MULTIPLE_STATEMENTS"}},
        )

    add(
        "csv/basic_valid.csv",
        csv_text(
            "Booking Date,Description,Amount,Currency,IBAN,Reference,Balance",
            [
                [
                    D1,
                    "Test contribution",
                    "500.00",
                    "GBP",
                    ACCOUNT,
                    "SYNTH-PAY-1",
                    "500.00",
                ],
                [
                    D2,
                    "Test materials",
                    "-18.75",
                    "GBP",
                    ACCOUNT,
                    "SYNTH-PAY-2",
                    "481.25",
                ],
            ],
        ),
        core(
            [
                tx("500.00", "Test contribution", booking=D1, reference="SYNTH-PAY-1"),
                tx("-18.75", "Test materials", booking=D2, reference="SYNTH-PAY-2"),
            ],
            iban_value=ACCOUNT,
            end=D2,
            warnings=["CSV_BALANCE_ORDER_UNKNOWN"],
        ),
    )
    add(
        "csv/split_debit_credit.csv",
        csv_text(
            "Date,Narrative,Debit,Credit,Currency,Account",
            [
                [D1, "Test contribution", "", "500.00", "GBP", "SYNTH-ACCOUNT-1"],
                [D2, "Test materials", "18.75", "", "GBP", "SYNTH-ACCOUNT-1"],
            ],
        ),
    )
    add(
        "csv/all_fields.csv",
        csv_text(
            "Booking Date,Value Date,Description,Amount,Currency,Account,Transaction ID,Reference,Customer Code",
            [
                [
                    D1,
                    D2,
                    "Test invoice",
                    "-9.25",
                    "GBP",
                    "SYNTH-ACCOUNT-1",
                    "SYNTH-TX-1",
                    "SYNTH-INV-1",
                    "SYNTH-CUSTOM-1",
                ]
            ],
        ),
        core(
            [tx("-9.25", "Test invoice", D1, D2, "SYNTH-INV-1", "SYNTH-TX-1")],
            account="SYNTH-ACCOUNT-1",
            end=D2,
        ),
    )
    for name, headers, row, code in [
        (
            "ambiguous_amount",
            "Booking Date,Description,Amount,Currency",
            [D1, "Test invoice", "1,234", "GBP"],
            "AMBIGUOUS_AMOUNT",
        ),
        (
            "negative_debit",
            "Booking Date,Description,Debit,Credit,Currency",
            [D1, "Test invoice", "-18.75", "", "GBP"],
            "SIGNED_DEBIT_CREDIT",
        ),
        (
            "duplicate_header",
            "Booking Date,Description,Amount,Amount,Currency",
            [D1, "Test invoice", "3.00", "4.00", "GBP"],
            "AMBIGUOUS_COLUMNS",
        ),
        (
            "malformed_row",
            "Booking Date,Description,Amount,Currency",
            [D1, "Test invoice", "3.00", "GBP", "SYNTH-EXTRA"],
            "INVALID_CSV_ROW",
        ),
    ]:
        add(f"csv/{name}.csv", csv_text(headers, [row]), {"error": {"code": code}})

    for fields, name in [(False, "basic_valid"), (True, "all_fields")]:
        camt_txs = [
            tx(
                "-18.75",
                "Test materials\nTest receipt 7" if fields else "Test materials",
                D2,
                D2,
                "SYNTH-E2E-1",
                name="Synthetic Workshop",
                counterparty=OTHER if fields else None,
            ),
            tx(
                "80.00",
                "Test contribution",
                D3,
                D3,
                "SYNTH-E2E-2",
                name="Synthetic Sponsor",
            ),
        ]
        add(
            f"camt053/{name}.camt053.xml",
            camt_document(camt_statement(all_fields=fields)),
            core(
                camt_txs,
                iban_value=ACCOUNT,
                identity="SYNTH-CAMT-1",
                sequence="1",
                opening="500.00",
                closing="561.25",
            ),
        )
    add(
        "camt053/multiple_statements.camt053.xml",
        camt_document(
            camt_statement() + "\n" + camt_statement(identity="SYNTH-CAMT-2")
        ),
        {"error": {"code": "MULTIPLE_STATEMENTS"}},
    )

    for name, memo, encoding in [
        ("basic_valid", "Test materials", "ascii"),
        ("windows1252", "Test café materials", "cp1252"),
    ]:
        add(
            f"ofx/{name}.ofx",
            ofx_document(ofx_scope(memo=memo)),
            core(
                [
                    tx("-18.75", memo, booking=D2, identity="SYNTH-OFX-1"),
                    tx(
                        "80.00", "Test contribution", booking=D3, identity="SYNTH-OFX-2"
                    ),
                ],
                closing="561.25",
            ),
            encoding,
        )
    add(
        "ofx/basic_valid.qfx",
        ofx_document(ofx_scope(card=True, account="SYNTH-QFX-CARD-1"), card=True),
        core(
            [
                tx(
                    "-7.00",
                    "Test card purchase",
                    booking=D2,
                    identity="SYNTH-QFX-1",
                    currency="USD",
                )
            ],
            account="SYNTH-QFX-CARD-1",
            currency="USD",
            end=D2,
            closing="-7.00",
        ),
    )
    add(
        "ofx/multiple_statements.ofx",
        ofx_document(ofx_scope() + ofx_scope(account=OTHER)),
        {"error": {"code": "MULTIPLE_STATEMENTS"}},
    )

    inventory = {
        "version": 2,
        "authored_on": "2026-10-09",
        "author": "Codex, commissioned by the project maintainer",
        "license": "MIT",
        "construction": "Literal invented scenarios in corpus/generate.py; no input samples or parser output consumed",
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": [
            {
                "path": "corpus/" + path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "provenance_status": "independently_authored",
                "publication_permission": "project_MIT",
            }
            for path, data in sorted(files.items())
        ],
    }
    files["provenance.json"] = (json.dumps(inventory, indent=2) + "\n").encode()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = artifacts()
    mismatches = []
    if args.check:
        for family in ("mt940", "csv", "camt053", "ofx"):
            for target in (ROOT / family).iterdir():
                if target.is_file() and str(target.relative_to(ROOT)) not in files:
                    mismatches.append(str(target.relative_to(ROOT)) + " (unrecorded)")
    for path, data in files.items():
        target = ROOT / path
        if args.check:
            if not target.is_file() or target.read_bytes() != data:
                mismatches.append(path)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    if mismatches:
        parser.exit(1, "Generated files differ: " + ", ".join(mismatches) + "\n")
    print(f"{'Verified' if args.check else 'Wrote'} {len(files)} corpus artifacts")


if __name__ == "__main__":
    main()
