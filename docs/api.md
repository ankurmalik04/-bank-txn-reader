# Python API

This guide describes BankParser 0.5.0a1, JSON schema 1.1. Install the
base package for MT940 and native CSV; add extras for CAMT.053, OFX/QFX and
alternative implementations. See [installation](../README.md#install).

## Parse one statement

```python
from bankparser import CsvOptions, parse

result = parse(
    "statement.csv",
    csv_options=CsvOptions(decimal_separator=",", grouping_separator="."),
)
```

`parse(source, *, implementation=None, csv_options=None)` accepts a filesystem
path (`str` or `os.PathLike`) or `bytes`. It detects format from content and
returns `ParseResult`. Input must be non-empty and at most 5 MiB. File reads are
bounded even if the file grows between the size check and reading.

`implementation` selects a registered implementation for the detected format:

| Format | Default | Alternative |
| --- | --- | --- |
| `csv` | `native` | `bankstatementparser` with `alternative` or `all` |
| `mt940` | `wolph` | `bankstatementparser` with `alternative` or `all` |
| `camt053` | `bankstatementparser` with `camt` or `all` | None |
| `ofx` | `ofxparse` with `ofx` or `all` | `bankstatementparser` with `alternative` or `all` |

An unknown implementation raises `UnknownImplementationError`; a missing
optional dependency raises `ParserDependencyError`. These exception classes
are available from `bankparser.errors` and inherit `BankParserError`.

## Result and semantics

| Field | Contents |
| --- | --- |
| `schema_version` | Version of the serialized canonical contract: `"1.1"`. |
| `source` | Format, implementation and package versions; basename for path inputs, otherwise `file_name=None`. |
| `account` | Available account identifier, IBAN and currency. |
| `statement` | Identifier, sequence, dates, opening/closing balances and their currencies. |
| `transactions` | Ordered tuple of movements, with `Decimal` amounts, dates, descriptions, counterparties, reference, ID and raw metadata. |
| `validation` | Aggregate status and the individual checks. |
| `warnings` | Tuple of parse warnings, each with a code, message and optional location. |

Incoming movements are positive and outgoing movements are negative. Missing
fields remain `None`; no booking date is invented from a missing MT940 entry
date. An account identifier is not automatically certified as an IBAN.

MT940 statement dates prefer balance boundaries, with transaction-date fallbacks
when a boundary is absent. CSV dates describe the observed activity range. See
[format conventions](compatibility.md#format-specific-conventions) for CAMT/OFX.

Default OFX booking dates retain the source calendar day before UTC conversion.
Original `DTPOSTED`/`DTUSER`/`DTAVAIL` text and direct transaction fields remain in
`transaction.raw["source_fields"]`, with `source_path` identifying the source
record. `DTUSER` is not promoted to a value date. Ledger balance stays a closing
balance; available balance is not substituted for it. No opening balance is derived.

Dataclasses prevent field reassignment; their raw metadata dictionaries remain
mutable. Treat source metadata as read-only if using it as import evidence.
The result has no built-in file hash, idempotency key or deduplication state.

## CSV options

`CsvOptions` is a frozen dataclass with three optional fields:

| Option | Allowed values and effect |
| --- | --- |
| `decimal_separator` | `"."` or `","`; `None` accepts only unambiguous ungrouped amounts. |
| `grouping_separator` | `"."`, `","`, space or apostrophe; requires an explicit, different decimal separator. |
| `date_format` | An explicit `datetime.strptime` format, such as `"%d/%m/%Y"`. |

Passing `csv_options` for another format raises `InputError`. Invalid monetary
conventions raise errors; invalid or ambiguous dates stay `None` with an
`UNPARSED_TRANSACTION_DATE` warning. Generic Date and running Balance columns
retain their source values without establishing more specific semantics.

Native CSV preserves original cells in `transaction.raw["source_fields"]`, with
`source_line` containing the record's ending physical line. This includes
unrecognised columns and quoted multiline cells. Blank rows are skipped.
Malformed row widths, invalid quoting, duplicated semantic columns, conflicting
Amount/Debit/Credit columns and multiple account/currency scopes are rejected.
The standard-library CSV field-size limit also applies; overlong fields raise
`INVALID_CSV`.

The parser consumes rows incrementally, but `parse()` returns all transactions
and retains their original cells. It is not a streaming-result API.

## Validation and exceptions

`BALANCE_RECONCILIATION` checks opening balance plus signed movements against
closing balance using exact arithmetic. `CURRENCY_CONSISTENCY` checks available
account, transaction and balance currencies. `FINITE_AMOUNTS` rejects non-finite
canonical amounts and balances. Parsing isolates backend arithmetic from the
caller's Decimal context; validation chooses enough precision for its operands
and leaves caller settings unchanged.

`STATEMENT_DATE_ORDER` checks that the statement start does not exceed its end;
either missing bound skips it. Equal bounds pass. `TRANSACTION_CURRENCIES`
separately skips when any transaction currency is missing or blank, even when
available currencies agree. `TRANSACTION_BOOKING_DATES` checks inclusive known
statement bounds: an outside booking date fails; missing dates or bounds skip
an otherwise noncontradictory check. `TRANSACTION_VALUE_DATES` uses the same
interval but skips for outside value dates, since settlement may legitimately
cross reporting boundaries. Such exceptions require review; no grace period or
silent approval is applied. Reversed periods skip transaction date checks and
fail STATEMENT_DATE_ORDER. Empty activity passes transaction completeness checks.
`ACCOUNT_IDENTITY` requires a nonblank account
ID or IBAN to pass, without independently verifying ownership or validity.
Missing identity skips that check and adds `MISSING_ACCOUNT_IDENTITY` at
`account`. Select and verify the destination account before importing.

Aggregate status is `failed` if any check fails, otherwise `warning` if a check
is skipped, otherwise `passed`. Parse warnings do not change that aggregate
status. Inspect both the warnings and checks before importing movements.
Generic CSV normally has missing statement balances and thus a skipped balance
check. No opening balance is reverse-derived merely to make the check pass.

Catch `BankParserError` for expected loading/detection/parsing failures. Every
library exception has `code` and nullable `location`:

| Code | Typical response |
| --- | --- |
| `INPUT_ERROR` | Check the path, input size or option configuration. |
| `UNSUPPORTED_FORMAT` | Export a supported structured format. |
| `UNSUPPORTED_ENTRY_STATUS` | CAMT.053 entries require `BOOK`; supply booked entries with an explicit status. |
| `SIGNED_CAMT_AMOUNT` | CAMT amounts must be non-negative magnitudes; `CdtDbtInd` supplies the sign, including for balances. |
| `MISSING_DEPENDENCY` | Install the format's extra or select an installed implementation. |
| `UNKNOWN_IMPLEMENTATION` | Inspect `implementations(format)`. |
| `MULTIPLE_STATEMENTS` | Split the input into supported statement/account scopes. |
| `AMBIGUOUS_AMOUNT` | Supply explicit decimal/grouping conventions. |
| `INVALID_AMOUNT`, `SIGNED_DEBIT_CREDIT`, `AMBIGUOUS_MOVEMENT` | Correct the amount/sign convention or use a signed Amount column. |
| `AMBIGUOUS_COLUMNS`, `INVALID_CSV_ROW`, `INVALID_CSV` | Correct the CSV header, structure or encoding. |
| `EMPTY_STATEMENT` | Supply a CSV containing transaction rows. |
| `TRANSACTION_COUNT_MISMATCH` | Review the source/backend mismatch; do not import a partial result. |
| `INVALID_OFX_STRUCTURE`, `INVALID_DATE` | Correct malformed, truncated, duplicate-field or invalid-date OFX input. |
| `DUPLICATE_TRANSACTION_ID` | Resolve duplicate FITIDs within the statement; the parser does not deduplicate. |
| `UNSUPPORTED_CORRECTION`, `UNSUPPORTED_PENDING_ACTIVITY`, `UNSUPPORTED_TRANSACTION_CURRENCY`, `UNSUPPORTED_OFX_SCOPE`, `UNSUPPORTED_OFX_PROFILE` | Export a supported single bank/card statement without these financial features. |
| `OFX_RESPONSE_ERROR` | Resolve the bank's error response before importing. |
| `OFX_BACKEND_ERROR`, `OFX_BACKEND_MISMATCH`, `INCOMPLETE_OUTPUT` | Review the source/backend failure; no partial result is returned. |
| `PARSE_ERROR` | Review the message and provide a minimal synthetic reproducer. |

This is a list of common codes, not an exhaustive enumeration. More specific
encoding, date, balance and transaction errors exist; do not depend on message
wording for control flow.

## Compare and serialize

`implementations(format)` lists configured names without importing optional
backends. It does not certify their dependencies are installed.

`compare(source, *, implementations=None, csv_options=None)` reads one bounded input snapshot,
runs the selected implementations and returns `ComparisonReport`: `format`,
`implementations`, `matches` and `differences`. Each difference contains a field
path and the value from each implementation. Provenance/raw metadata are excluded.
At least two distinct implementations are required; failures abort comparison.
An explicit selection runs only those implementations, without invoking an
unselected default. Omitted selection uses all configured implementations.

CSV options apply to every selected implementation; non-CSV input rejects them.
The CLI comparison accepts `--decimal-separator`, `--grouping-separator` and
`--date-format` too:

```python
from bankparser import CsvOptions, compare

data = b'Booking Date,Amount,Currency\n2026-10-01,"1,234",GBP\n'
options = CsvOptions(decimal_separator=".", grouping_separator=",")
report = compare(data, implementations=("native", "bankstatementparser"),
                 csv_options=options)
```

This requires the optional backend. The CSV compatibility adapter shares native
field mapping and adds count checking, so agreement does not independently prove
field extraction. Transaction amounts, balances and balance-reconciliation
expected/actual values compare numerically without rounding; decimal scale and
signed zero alone do not produce differences. Reported differences retain the
original serialized values. Other fields, including numeric-looking references,
compare exactly. `compare_results(mapping)` offers the same comparison for
already-parsed results.

Use `bankparser.serialization.to_primitive(value)` before JSON serialization.
Amounts become strings, dates become ISO strings, and tuples become lists.
Schema changes and migration instructions are recorded in [CHANGELOG.md](../CHANGELOG.md).
