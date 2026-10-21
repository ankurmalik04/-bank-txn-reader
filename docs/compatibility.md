# Compatibility and conformance

This describes BankParser 0.5.0a1, schema 1.1. Coverage is established by synthetic
fixtures and regression tests. It does not certify a bank, every version of a
format, or every document an upstream parser accepts.

The next evidence milestone follows the [bank/exporter sample conformance plan](conformance-plan.md): 3–5 permitted profiles with independently reviewed expectations and held-out samples. These profiles are planned, not established support.

## Install and scope

| Format | Implementation | Installation | Supported scope |
| --- | --- | --- | --- |
| MT940 | `wolph` (default) | Base package | One statement; repeated boundaries are rejected. |
| MT940 | `bankstatementparser` | `alternative` or `all` extra | The same statement scope; source booking dates/references are preserved independently. |
| CAMT.053 | `bankstatementparser` | `camt` or `all` extra | One `Stmt`; details must be representable by the backend and their count must match source details. |
| OFX/QFX | `ofxparse` (default) | `ofx` or `all` extra | One bank/card response, with strict source checks and local booking dates. |
| OFX/QFX | `bankstatementparser` | `alternative` or `all` extra | Earlier compatibility backend and parsing policies. |
| CSV | `native` (default) | Base package | One account/currency scope; recognized, non-duplicated headers. |
| CSV | `bankstatementparser` compatibility adapter | `alternative` or `all` extra | Native canonical fields plus the optional backend transaction-count check. |

The optional backend is pinned to `bankstatementparser==0.0.20`. The regression
suite has been exercised with WoLpH `mt-940` 5.1.1. The base install does not
import or install the optional backend. OFX uses `ofxparse==0.21` and `defusedxml`,
with BeautifulSoup/lxml dependencies but no pandas or NumPy. Extras require
`lxml>=6.1.3,<7`. CAMT and alternative
adapters bring pandas and other upstream dependencies. Some adapters use temporary
local files, removed after parsing; local processing is not a promise that files never reach disk.
Native CSV and default OFX parsing do not create temporary files. The `csv` extra
is retained as a compatibility alias with no additional dependencies.

Inputs are limited to 5 MiB. PDF/image extraction, bank connections and ledger
matching are outside this library's current support. Splitting multi-statement
files is the caller's responsibility.
The [API guide](api.md) describes signatures, errors, result fields and memory
behaviour. The support policy describes the maintenance scope for alpha releases.

## Fields checked by the golden fixtures

Successful golden tests assert all fields below. They exclude environment-specific
source metadata and parser-specific `raw`; selected raw fields have separate tests.
Null values are explicit assertions, not evidence that a format can never supply
that field.

| Object | Asserted fields |
| --- | --- |
| Account | `id`, `iban`, `currency` |
| Statement | `id`, `sequence`, `start_date`, `end_date`, `opening_balance`, `closing_balance`, `opening_balance_currency`, `closing_balance_currency` |
| Transaction | `booking_date`, `value_date`, `amount`, `currency`, `description`, all three `counterparty` fields, `reference`, `transaction_id` |
| Validation | Aggregate status; each check's code, status, expected and actual values |
| Warnings | Complete set of warning codes |

Transaction counts and order are asserted by comparing complete transaction lists.
Core golden tests do not freeze message wording or parser versions. Warning
locations and exception codes are covered by targeted tests. Comparison excludes
provenance/raw, but includes every other canonical field.

## Corpus and demonstrated behavior

| Family | Fixtures | What they check |
| --- | --- | --- |
| MT940 | `basic_valid`, `balance_mismatch`, `missing_description`, `reversals`, `missing_opening_balance`, `missing_closing_balance` | Signed movements and reversals, exact fixture amounts, identity/sequence, booking/value dates, references, descriptions and missing-balance outcomes across both implementations. |
| MT940 | `no_activity` | Empty transaction list with valid opening/closing balances across both implementations. |
| MT940 | `multiple_accounts`, `multiple_statements` | Two accounts with zero net movements are rejected before they can be misattributed. |
| MT940 | `currency_conflict` | WoLpH exposes both balance currencies and validation fails despite matching arithmetic. The alternative backend rejects the conflicting currencies during parsing. |
| CAMT.053 | `basic_valid`, `all_fields` | Namespace `.053.001.02`; signed entries, separate dates, opening/closing currencies, unstructured remittance, wrapped party names, references and counterparty IBAN. Separate assertions cover structured references, instruction IDs and source paths in raw metadata. |
| CAMT.053 | `multiple_statements` | Multiple `Stmt` nodes are rejected. |
| OFX/QFX | `basic_valid.ofx`, `basic_valid.qfx`, `windows1252` | Bank/card scopes, FITID, booking dates, signed movements, descriptions, ledger balance and declared Windows-1252 text. |
| OFX/QFX | `multiple_statements` | Multiple statement responses are rejected. |
| CSV | `basic_valid`, `split_debit_credit`, `all_fields` | Signed Amount or unsigned Debit/Credit columns, independent booking/value dates and ID/reference fields, missing statement balances and preservation of unmapped cells. |
| CSV | `ambiguous_amount`, `negative_debit`, `duplicate_header`, `malformed_row` | Explicit rejection codes for ambiguity, sign contradictions, duplicate mappings and malformed rows. |

These fixtures contain 24 source files. Existing basic cases are run by the
format conformance suites; new regressions are listed in `corpus/regressions.json`.
Expected values are authored from the synthetic sources independently of parser
output. The MT940 cross-parser test now includes dates, references and counterparties.

## Format-specific conventions

**MT940:** Tested fixtures are UTF-8 text with line-start tags. The parser rejects
repeated message/account/statement/balance boundaries. Booking dates use the
entry date when present; the alternative adapter chooses the closest year to the
value date and leaves the booking date null when the entry date is absent.
Statement periods prefer opening/closing balance dates, falling back to
transaction dates when a boundary is absent. Bank/customer references remain
distinct in raw metadata. Country-specific `:86:` enrichment is inherited from
the selected backend and is not certified by the current corpus. Final balances
are used; intermediate balance support is not established by these fixtures.
UTF-8 BOM inputs are checked across both implementations. LF and CRLF are
accepted; CR-only MT940 files are not detected. Intermediate `60M`/`62M` balances
are not exposed consistently across implementations and are not covered by the
final-balance compatibility promise.

**CAMT.053:** Source nodes enrich the backend's ordered transaction records after
a count check. In unreleased source, ordered composite keys (booked amount,
currency, direction, account, booking/value dates, EndToEndId and AcctSvcrRef)
must also agree before enrichment. Reordered or changed records raise
`TRANSACTION_ALIGNMENT_MISMATCH`; indistinguishable source keys raise
`AMBIGUOUS_TRANSACTION_ALIGNMENT`, including repeated charges without enough
distinguishing evidence. Counts alone are insufficient. No automatic reordering
or deduplication occurs. The declared account currency is preserved independently of entry
and balance currencies, so contradictions fail `CURRENCY_CONSISTENCY` validation.
Entries require status `BOOK`, in either direct `Sts` or wrapped `Sts/Cd` form;
missing, pending, informational or unknown statuses raise
`UNSUPPORTED_ENTRY_STATUS` before transaction extraction. This does not establish
XSD conformance for either status shape. Unstructured remittance lines are joined
with newlines. Supported
direct/wrapped debtor and creditor names and IBAN/other account IDs are retained;
the fixture verifies the wrapped creditor form. `reference` prioritizes a
meaningful EndToEndId, then the backend reference, then AcctSvcrRef. Other payment
references and structured remittance references remain in raw metadata. Only the
documented namespace/version has corpus coverage; this is not full ISO 20022/XSD
validation. Multi-detail conservation remains an upstream check and has no
independent batch fixture in this release.

In the unreleased source, reporting-period bounds prefer explicit FrToDt/FrDtTm
and ToDtTm, preserving source-local dates; each absent bound falls back to the
OPBD/CLBD balance date. Empty, malformed or duplicate explicit bounds raise
`INVALID_STATEMENT_DATE`; reversed bounds fail shared date-order validation.
Meaningful Refs/TxId maps to `transaction_id`, independently of EndToEndId in
`reference`. Missing, empty or NOTPROVIDED IDs remain null; identifiers require
account/statement context and are not guaranteed unique. Published 0.5.0a1 uses
balance dates and leaves CAMT transaction_id null; see the changelog.

**OFX/QFX:** The default `ofxparse` adapter supports the exercised single bank/card
profile: SGML headers `OFXHEADER:100`, `DATA:OFXSGML`, version 102/103/160,
unencrypted/uncompressed input; or well-formed, unnamespaced XML. SGML leaf end
tags may be omitted; aggregates must close explicitly. Both paths reject
attributes, mixed content, duplicate financial fields and nesting over 64 levels.
SGML markup in text must be escaped; five XML predefined entities and numeric
character references are decoded once. Bare SGML ampersands remain literal.
XML DTDs, declared entities and external references are rejected using defusedxml.
This is a supported-profile check, not complete OFX schema/version validation.

UTF-8, declared Windows-1252, Latin-1 and UTF-16 XML with a BOM have targeted
checks; ASCII is also supported. Invalid declarations raise `INVALID_ENCODING`.
Transactions require a nonempty, unique FITID, plain finite TRNAMT and valid
DTPOSTED. OFX date-only or complete time forms are accepted, with optional
fractional seconds/timezone suffixes. Booking dates retain the reported local
calendar day; raw source fields preserve original timestamps. DTUSER/DTAVAIL
are checked when present but do not establish value-date semantics.

Corrections, pending transactions/lists, transaction currency aggregates and
investment/loan statements raise explicit unsupported-feature errors. Present
response statuses must have code zero and INFO/WARN severity; WARN is surfaced.
Missing status is permitted by this fixture profile. Duplicate FITIDs are rejected
even for identical records; there is no cross-file deduplication.

The backend must agree with source account, currency, ledger balance and ordered
transaction IDs/amounts. Discarded entries or count disagreement fail parsing;
backend financial warnings are exposed. Opening balance is not manufactured.
Closing balance uses LEDGERBAL, never AVAILBAL, with currency from CURDEF.
Counterparty/value-date enrichment, full investment/loan support and preservation
of every nested extension field are outside this profile. Direct transaction leaf
fields remain in raw metadata. Calls through BankParser serialize backend access
because ofxparse stores options on its class; direct external use of that class
is outside this concurrency protection. Upstream BeautifulSoup deprecation
warnings can still appear through Python's warning system.

Explicit `bankstatementparser` retains its earlier parsing policy and does not
provide all the default adapter's strict source checks. It remains useful for
compatibility comparisons; agreement on basic fixtures is not broader conformance
evidence. Representative bank exports remain an outstanding coverage requirement.

**CSV:** UTF-8/UTF-8 BOM, comma/semicolon/tab/pipe separators, and the synonyms
listed in `src/bankparser/detection/csv.py` are recognized. Header rows must be
single-line; duplicate headers or multiple columns for one semantic field are
rejected. Booking Date and Value Date are distinct; generic Date is preserved in
raw without being promoted to either. Statement start/end describe the observed
date range, not a certified statement period.
The default `native` implementation reads rows incrementally, retains original
cells once in transaction metadata, and tracks date extrema and unique warnings
while parsing. It does not construct a DataFrame or perform a backend round trip.
The public API still reads at most 5 MiB and materializes the complete result.
Header-only files raise `EMPTY_STATEMENT`; no opening/closing balances are inferred.
The optional CSV compatibility adapter shares native field mapping, so comparison
agreement does not provide independent evidence about those fields.

Ungrouped integer and unambiguous decimal amounts are accepted. A sole separator
followed by three digits, repeated separators, or mixed separators require
explicit `CsvOptions`. Grouped amounts validate group sizes. Debit and Credit
cells must be non-negative, and cannot both be non-zero. A file cannot contain
both an Amount column and Debit/Credit columns. Currency symbols and scientific
notation are unsupported. Running balances stay opaque source cells because
ordering and balance timing are not inferred. Invalid/ambiguous transaction dates
stay null with a warning; an explicit `date_format` resolves supported ambiguity.

## Validation boundaries

CAMT `Amt` elements and OFX `TRNAMT`/`BALAMT` fields require plain decimal
notation before backend arithmetic. Exponent notation, non-finite values and
invalid monetary text raise `INVALID_AMOUNT` with a source location. Precision
and fractional scale remain bounded by source length rather than an arbitrary
28-digit limit. This guard is not full schema validation.
CAMT amounts are non-negative magnitudes, with `CdtDbtInd` supplying direction.
Negative source magnitudes, including negative zero, raise `SIGNED_CAMT_AMOUNT`
before backend arithmetic. This applies to entry, detail and balance `Amt` nodes.

Optional DataFrame adapters normalize missing scalar values, including NaN,
NaT and nullable sentinels, before text/date mapping. Missing references remain
null unless a real documented fallback is available. Literal source text such
as `nan` remains text.

`BALANCE_RECONCILIATION` checks opening plus signed transactions against closing
when both balances exist. `CURRENCY_CONSISTENCY` checks available account,
transaction and opening/closing balance currencies. A missing prerequisite skips
a check and gives aggregate `warning`; contradictions give `failed`.
`STATEMENT_DATE_ORDER` fails reversed statement bounds, passes equal or ordered
bounds and skips when either is absent. In unreleased source,
`TRANSACTION_CURRENCIES` separately marks missing/blank transaction currencies
incomplete. Booking dates outside inclusive known bounds fail
`TRANSACTION_BOOKING_DATES`; missing dates/bounds skip unless a known bound is
already contradicted. `TRANSACTION_VALUE_DATES` marks outside value dates
incomplete for review, allowing legitimate settlement boundary exceptions without
claiming completeness. Missing dates/bounds also skip; reversed bounds skip both
range checks. No automatic grace period applies. Empty activity passes these
transaction checks. `ACCOUNT_IDENTITY` passes when a nonblank account ID or
IBAN is present; otherwise it skips and parsing adds `MISSING_ACCOUNT_IDENTITY`.
Generic CSV may omit identity, but callers must select and verify the destination
account. The presence check does not certify the identifier or its ownership.

Backend adapters check source transaction counts against emitted records. Native
CSV creates one transaction for every accepted non-blank source row. Equal counts
and passing balance arithmetic do not prove every field was extracted correctly.
`FINITE_AMOUNTS` rejects non-finite transaction amounts and balances; balance
arithmetic is skipped for those values.
Balance arithmetic chooses precision from the canonical operands. Public parsing
isolates backend Decimal arithmetic from the embedding application's context;
neither operation changes the caller's settings.

These checks do not establish document authenticity, duplicate-import safety,
continuity between statements, or reconciliation against an accounting ledger.
