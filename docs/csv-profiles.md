# Explicit CSV mappings and parsing profiles

The unreleased CSV configuration API adds explicit source meanings without
changing canonical schema 1.1. Existing automatic headers, date ambiguity,
exact amounts, row-width checks and single account/currency scope remain the
default. Profiles describe supported settings, not certified bank compatibility.

## Python and CLI

```python
from bankparser import CsvOptions, parse

options = CsvOptions(
    columns={"Posting Date": "booking_date", "Net": "amount", "Text": "description"},
    date_format="%d/%m/%Y",
    default_currency="GBP",
    expected_currency="GBP",
)
result = parse("statement.csv", csv_options=options)
```

Mappings are **source header → canonical field**. They replace all synonym
matching, including for recognized headers. Every mapped source header must
exist, and targets must be unique. Extra columns stay in source raw metadata
but have no canonical meaning. Source header matching is exact after stripping
outer whitespace; explicit mapping supports Unicode headers and distinguishes
case/punctuation. Automatic matching retains its existing normalization and
ambiguity guards. Exact duplicate/blank headers are always rejected.

```sh
bankparser parse statement.csv --map 'Posting Date=booking_date' --map Net=amount --map Text=description --date-format '%d/%m/%Y' --default-currency GBP --expected-currency GBP --json-errors
```

All CSV flags also work for `compare`, including `--fail-on-diff`. Supply a file
and its known conventions; file extensions do not establish the format.
`parse` and `compare` accept `format="csv"` (CLI `--format csv`) to declare CSV
explicitly. CSV options/profile also declare CSV for an otherwise unrecognized
input. Recognized CAMT/OFX/MT940 cannot be reinterpreted by forcing CSV. The CSV
adapter still requires at least two header cells, an amount/debit/credit field
and date/description/account context, valid rows, finite monetary values and
one scope. Limits and validation remain active. No other format override exists.

## Fields and monetary meaning

Allowed mapping targets:

| Target | Meaning |
| --- | --- |
| `booking_date`, `value_date` | Explicit source date role. |
| `date` | Generic date; remains ambiguous unless `date_role` is set. |
| `amount` | Signed account-booked amount; incoming positive, outgoing negative. |
| `debit`, `credit` | Non-negative outgoing/incoming magnitudes. |
| `currency` | Source transaction/account currency. |
| `description`, `reference`, `transaction_id` | Separate canonical text/identity fields. |
| `account_id`, `iban` | Explicit account identity meanings; IBAN is not inferred from an arbitrary mapped identifier. |
| `balance` | Preserved raw running-balance text; no opening/closing balance is inferred. |

Never map signed Amount together with Debit/Credit. Simultaneously nonzero debit
and credit, negative split magnitudes, missing amounts and ambiguous monetary
separators are still rejected. Mapping a field does not infer bank-specific sign
reversal, locale, pending/booked activity or balance timing. Both account ID and
IBAN can be present and differ; each participates in the scope boundary. A lone
explicit IBAN supplies account.id as the existing canonical identity fallback.

`decimal_separator`, `grouping_separator` and `date_format` keep their existing
semantics. Without an explicit format, ambiguous dates remain null with warnings.
Invalid configured dates also remain null with an `UNPARSED_TRANSACTION_DATE`
warning. Generic `date` maps to booking or value only with
`date_role="booking_date"` or `"value_date"`; an existing column for that same
role causes `AMBIGUOUS_COLUMNS`. Without a generic date column, date_role has no
effect. Original date text remains in source_fields.

## Currency fallback versus constraint

`default_currency` fills only an absent/blank source currency. It never replaces
a source value. Each fill adds `CONFIGURED_CURRENCY` (first location retained),
and raw provenance labels it `configured-default`. Source values remain intact.

`expected_currency` requires the effective currency to match. Missing effective
currency or a conflicting source currency raises `CSV_CURRENCY_CONSTRAINT`.
It supplies no currency by itself. Use both options when you need a fallback and
an assertion. Contradictory default/expected options are rejected at configuration
time. Option values must be three ASCII letters and are normalized to uppercase.
A fallback on some rows and incompatible source values on others still fails the
single-scope guard. There is no foreign-exchange conversion.

## Header location, delimiters and encoding

| Option | Meaning |
| --- | --- |
| `header_row` | Exact 1-based physical start line, 1–10000. Blank lines count; a line inside a quoted multiline record is not a valid start. |
| `header_search_limit` | Search the first N physical lines, 1–200; candidate headers must end inside that window. Multiple plausible headers require explicit header_row. |
| `delimiter` | Explicit comma, semicolon, tab or pipe; otherwise select deterministically from those delimiters. |
| `encoding` | Explicit `utf-8-sig` (default, accepts UTF-8 with/without BOM), `utf-8`, `cp1252`/`windows-1252`, or `iso-8859-1`/`latin-1`. No encoding guessing. |

Header row and search limit are mutually exclusive. Without either, the first
nonblank CSV record is the header, preserving existing behavior. Blank data rows
are skipped; multiline cells are preserved. Configured raw metadata records the
header start/end physical lines and each transaction's source_line_start.
The existing source_line remains the data record's ending physical line. Error
locations use physical ending lines and original source column names. No footer
skipping or automatic multi-account splitting is supported.

## Reusable data-only profiles

```python
from bankparser import load_csv_profile, parse, compare

profile = load_csv_profile("examples/csv-profiles/euro-split.profile.json")
result = parse("examples/csv-profiles/euro-split.csv", csv_profile=profile)
# Requires both registered implementations to be installed:
report = compare("examples/csv-profiles/euro-split.csv", csv_profile=profile)
```

```sh
bankparser parse examples/csv-profiles/euro-split.csv --csv-profile examples/csv-profiles/euro-split.profile.json
bankparser compare examples/csv-profiles/euro-split.csv --csv-profile examples/csv-profiles/euro-split.profile.json --fail-on-diff --json-errors
```

A profile has exactly `profile_schema_version: "1"`, nonblank `id` and `version`,
`format: "csv"` and an `options` object containing CsvOptions fields. See the
[JSON Schema](schemas/csv-profile-v1.schema.json). The loader reads at most 64 KiB
of UTF-8 JSON, rejects duplicate/unknown keys and invalid types/options, and never
imports or evaluates exporter code. It records the exact profile-file SHA-256;
the hash identifies bytes, not authenticity or support certification.

You can also construct `CsvProfile(id="my-export", version="1", options=options)`
in Python. Such profiles have no file digest. Profile and option overrides are
mutually exclusive in Python and CLI; create a deliberately versioned modified
profile instead of silently layering contradictory meanings. Existing first-three
positional `CsvOptions` arguments remain supported. The copied columns mapping
is immutable; use options.to_dict() for JSON-safe configuration, or the existing
to_primitive serializer (now handles immutable mappings too).

## Provenance and compatibility

Configured transactions add raw.csv_configuration with the effective option set,
selected header start/end lines, currency origin and optional profile id/version/
file hash. Original cells remain in raw.source_fields; preamble text is not
reclassified as transactions. These raw additions and CONFIGURED_CURRENCY are
observable. Canonical dataclass fields and schema 1.1 do not change. Configured
currency/date roles are user-supplied interpretations, not new bank source facts.
Default unconfigured CSV output stays compatible with existing corpus goldens.

The optional bankstatementparser CSV adapter still uses native canonical mapping
and adds only a backend count check. It now receives normalized UTF-8 columns so
custom headers, encodings and preambles work consistently; agreement does not
independently verify extracted financial fields. Source raw metadata is unchanged
by the normalized temporary backend input.

Five synthetic profiles and independently invented complete expectations cover:
custom signed headers with ignored extra columns; semicolon European split
amounts and preamble; cp1252 tab export with currency fallback and generic value
date; Unicode pipe headers with multiline text; and a BOM/debit-only export with
an exact header after multiline preamble plus separate account ID/IBAN. These
are regression evidence, not representative production or held-out exports.

The conformance runner accepts these expanded inline CsvOptions too. Its manifest
and report v1 schemas gain optional configuration fields without changing the
required structure. Financial expectations and private evidence rules remain
unchanged; the CSV parsing-profile schema is separate from its evidence-profile
record. No runtime dependencies are added.
