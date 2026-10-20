# Changelog

## 0.5.0 — unreleased

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
