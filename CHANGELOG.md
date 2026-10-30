# Changelog

## Unreleased

- CAMT source guards now require exactly one valid CRDT/DBIT direction and
  booked amount for each entry/balance. Detail directions inherit only when
  absent; blank/duplicate/unknown directions and conflicting single-detail signs
  are rejected before backend extraction. Missing/duplicate supported detail
  amounts/containers are rejected rather than selecting the first value.
- Each multi-detail CAMT entry must conserve its own signed booked total in its
  booked currency, independently of statement balances. Mixed-direction details
  use their reported signs; RvslInd never triggers a second inversion. Instructed
  amounts are not booked candidates and no currency conversion is inferred.
  The pinned backend already checks batch conservation; this adds independent
  wrapper enforcement and source-specific errors.
- CAMT raw metadata adds entry_amount (unsigned magnitude), entry_currency,
  entry_direction and optional amount_details (source paths, exact magnitudes
  and explicit currencies) to preserve entry/detail and foreign/instructed values
  separately from canonical booked amounts. Schema stays 1.1; public signatures
  and dependency pins are unchanged. Consumers must tolerate additive raw keys.
  Newly strict malformed-input errors are documented in docs/api.md.

- CAMT descriptions now fall back from unstructured remittance to AddtlTxInf,
  then AddtlNtryInf. An entry-level AcctSvcrRef is retained in raw metadata and
  used when existing canonical reference candidates are absent; EndToEndId and
  backend narrative precedence are unchanged.
- CAMT counterparty names, account IDs and IBANs now use one party role. When
  the usual role is absent on a return, all available fields come from the
  remaining role. An unnamed account never borrows the other party's name;
  zero movements use their reported credit/debit direction.
- Additional synthetic CAMT regressions cover both populated parties, partial
  and absent party data, blank fallback text, multiline remittance and missing
  EndToEndId values. Metadata-only changes are checked against independently
  authored financial expectations; missing identifiers are not borrowed or invented.

## 0.5.0a2 — 21 October 2026

- CAMT enrichment now verifies ordered source/backend keys comprising booked
  amount, currency, direction, account, dates, EndToEndId and AcctSvcrRef before
  combining metadata. Changed/reordered records raise TRANSACTION_ALIGNMENT_MISMATCH;
  indistinguishable source keys raise AMBIGUOUS_TRANSACTION_ALIGNMENT. Legitimate
  repeated charges remain distinct source records but can require a more explicit
  profile before they are accepted; no automatic reordering or deduplication occurs.
- Validation adds TRANSACTION_CURRENCIES for missing/blank transaction currencies,
  independently of conflicts among known currencies. It adds inclusive booking
  and value-date range checks. Missing dates/bounds are incomplete; out-of-range
  booking dates fail, while out-of-range value dates require review and give
  warning status. No automatic grace period is assumed. Strict CLI validation
  exits 3 on incomplete checks. Consumers must tolerate the added check codes;
  some previously passed reports now become warning/failed. Schema fields stay 1.1.

- CAMT statement bounds now prefer explicit FrToDt/FrDtTm and ToDtTm, preserving
  their source-local dates. Each absent bound falls back to its booked balance
  date. Invalid, empty or duplicate explicit bounds raise INVALID_STATEMENT_DATE;
  reversed bounds fail shared validation. Existing callers may observe different
  reporting dates when balance dates differ from the declared reporting period.
- CAMT transaction_id now preserves meaningful source Refs/TxId independently
  of reference (EndToEndId priority is unchanged). Missing, empty or NOTPROVIDED
  IDs remain null. IDs are not assumed globally unique or safe deduplication keys.
  Model fields and canonical schema version remain unchanged.

## 0.5.0a1 — first alpha

BankParser preserves statement balance currencies and additional transaction
fields, and rejects unsupported statement scopes and ambiguous CSV conventions.

### Migration from 0.4.1

- CAMT negative `Amt` magnitudes (including negative zero) raise
  `SIGNED_CAMT_AMOUNT` before backend arithmetic. `CdtDbtInd` supplies the sign;
  malformed negative debits can no longer become reconciled credits.
- Shared validation adds `STATEMENT_DATE_ORDER` and `ACCOUNT_IDENTITY` checks.
  Reversed bounds fail; missing date bounds or identity make validation incomplete
  (`warning`). Missing account ID and IBAN add `MISSING_ACCOUNT_IDENTITY`.
  Generic CSV remains accepted, with no invented identity. Strict CLI validation
  exits `3` for these incomplete checks. Present identity is not certified and
  transaction dates are not constrained to the statement period.
- Comparison now treats numerically equal monetary values as equal regardless
  of decimal scale, retaining original strings for actual differences. Other
  fields still compare exactly. Python `compare()` accepts `csv_options`; CLI
  comparison accepts all three CSV convention flags. Explicit selection invokes
  only the selected implementations. These changes add no dependencies or model
  fields; canonical schema stays `1.1`.

- Optional extras now require `lxml>=6.1.3,<7`, incorporating upstream XML
  entity-handling fixes. Environments retaining older lxml need an upgrade.
  Base MT940/native CSV dependencies remain unchanged.
- OFX/QFX now defaults to guarded `ofxparse==0.21`. The `ofx` extra installs
  `ofxparse` and `defusedxml` without pandas/NumPy; BeautifulSoup/lxml remain
  dependencies. Existing `bankstatementparser` calls require `alternative` or
  `all`. Default source metadata reports `ofxparse` and its version.
- Default OFX parsing validates XML or bounded SGML structure before the backend,
  supports BOM UTF-16 detection and Latin-1 `8859-1`, preserves the local booking
  day and raw timestamps, and rejects duplicate FITIDs, response errors,
  corrections, pending activity and transaction currency aggregates. This stricter
  profile can reject files the earlier backend repaired or partially represented.
  The canonical schema remains 1.1; raw metadata adds source fields and paths.
- CAMT preserves the declared account currency independently of entry/balance
  currencies, exposing contradictions through currency validation. Entries with
  missing or non-`BOOK` status now raise `UNSUPPORTED_ENTRY_STATUS` before
  transaction extraction.
- Optional DataFrame adapters normalize missing scalar sentinels before mapping
  text and dates; NaN/NaT no longer become literal identifiers or dates. Source
  strings named `nan` remain available as ordinary text.
- CAMT and OFX monetary fields reject exponent/non-finite notation with
  `INVALID_AMOUNT` before backend arithmetic, preventing short exponents from
  expanding into enormous reconciliation values. Plain decimal amounts retain
  exact precision, including amounts with more than 28 significant digits.
- Balance validation now preserves all significant digits independently of the
  caller's Decimal context. Public parsing also isolates backend arithmetic from
  caller precision, exponent limits and traps.
- MT940 detection accepts a UTF-8 BOM. File reads remain bounded if a source grows
  after the size check. Comparison reads one input snapshot for every implementation.
- CSV now defaults to the standard-library `native` implementation, included in
  the base package. The `csv` extra adds no dependencies. Explicit
  `implementation="bankstatementparser"` calls remain available with `alternative`
  or `all`; they retain backend count checking over native canonical mappings.
  CSV source metadata now reports `native` and the BankParser version by default.
- Native CSV consumes rows incrementally without temporary files, DataFrames or
  normalized copies. Original source cells remain in transaction metadata.
  Header-only CSV inputs raise `EMPTY_STATEMENT`.
- JSON schema version is now `1.1`. Statement objects add
  `opening_balance_currency` and `closing_balance_currency`; warnings add an
  optional `location`. Existing amount fields remain Decimal values in Python
  and strings in JSON. Consumers requiring exact object keys must update.
- MT940 files with repeated statement/account/balance sections raise
  `ParseError(code="MULTIPLE_STATEMENTS")`. Split them before calling `parse()`.
  CAMT and OFX also enforce one statement per file; CSV enforces one
  account/currency scope. Multiple CAMT transaction details are still permitted
  when the backend can conserve the entry total.
- The alternative MT940 adapter now preserves booking dates and customer/bank
  references. It no longer returns null for those supported source fields.
- CSV keeps Booking Date, Value Date, Transaction ID and Reference separately,
  and retains all original cells in `transaction.raw["source_fields"]`.
  Grouped or ambiguous amounts require `CsvOptions`. Negative Debit/Credit
  magnitudes and conflicting monetary columns raise explicit errors instead
  of producing a guessed movement. Use a signed Amount column when appropriate.
- CAMT preserves unstructured remittance text, wrapped/direct party names,
  supported counterparty accounts and structured references in raw metadata.
- Empty-activity MT940 statements with opening and closing balances are detected.
- OFX handles supported declared encodings, including Windows-1252. Invalid or
  unsupported encodings produce a structured error.
- CLI errors now go to stderr. Exit `3` means validation failed; with
  `--strict-validation`, it also means validation was incomplete. JSON results
  remain on stdout. Exit `2` means loading, detection or parsing failed.
- Exceptions expose `code` and optional `location`. `--json-errors` emits these
  fields on stderr for the parse command.
- Optional adapters are pinned to the independently tested
  `bankstatementparser==0.0.20`. The `all` extra installs all optional formats.

The corpus now checks every canonical transaction field rather than a smaller
projection that omitted descriptions, counterparties or references.
