# Onboard an unfamiliar CSV export

Start with one account and one currency in a file under 5 MiB. Keep the original
export and its exporter/version settings so you can explain every transformation.
This guide covers released 0.5.0a2 first; the profile workflow below is proposed
in [PR #6](https://github.com/ankurmalik04/-bank-txn-reader/pull/6).

## Establish the export's meanings

Check the header, delimiter, encoding, decimal/grouping separators, date order
and debit/credit convention against the exporter documentation and a few source
rows. An ambiguous `04/05/2026` or `1,234` needs an explicit convention. Identify
booking and value dates separately; a generic Date column has no automatic role
in 0.5.0a2. Signed Amount means incoming positive and outgoing negative; separate
Debit/Credit columns require non-negative magnitudes. Preserve repeated rows.

0.5.0a2 requires recognized headers and supports explicit amount separators and
date formats through `CsvOptions`. It does not have reusable profiles, arbitrary
header mappings, header-row selection or an explicit encoding option. When an
export needs those controls, use a reviewed copy converted to recognized headers
and UTF-8, retain the original, and document the conversion. Do not just rename
an ambiguous Date column without confirming its meaning.

## Run the current API example

From a source checkout with the base runtime installed:

```bash
PYTHONPATH=src python examples/csv_onboarding.py
```

In an unpacked source distribution with the runtime installed, omit PYTHONPATH.
The independently invented example uses semicolons, European amounts, explicit
day/month dates and a quoted description containing a delimiter. It asserts two
ordered movements, `-1234.50` and `12.50`, and separate booking/value dates. Its
warning status is expected because account identity and balances are absent.

For your own export with recognized headers:

```bash
bankparser parse export.csv --decimal-separator , --grouping-separator . --date-format '%d/%m/%Y' --json-errors
```

The date format in that command is a shell argument; in Python use
`CsvOptions(decimal_separator=",", grouping_separator=".", date_format="%d/%m/%Y")`.
JSON output and error details can contain financial data and identifiers. Inspect
them locally before sharing them.

## Check meaning before importing

Independently count source movements, check each sign/currency and date role,
and compare ordered descriptions, references, account identifiers and totals.
Calculate totals separately for each currency. A running Balance column remains
raw data in generic CSV; it does not establish statement opening/closing balances.
Inspect both validation checks and parse warnings. Missing currency, missing
dates and unknown account identity require resolution or explicit destination
review. A passing arithmetic check does not establish complete extraction.

| Symptom | Action |
| --- | --- |
| Ambiguous amount | Confirm separators, then pass explicit options. |
| Missing/ambiguous booking date | Confirm the source date role and format; inspect missing-date checks. |
| Multiple account/currency scopes | Export or independently split one scope per file. |
| Duplicate headers, bad quoting, wrong cell count | Correct the exporter settings or document a reviewed conversion; preserve the original. |
| Missing dependency | Native CSV uses the base install; installing all extras does not fix an ambiguous layout. |

## Reuse a profile after the profile feature is available

The commands in this section require the changes proposed in
[PR #6](https://github.com/ankurmalik04/-bank-txn-reader/pull/6); they are not
0.5.0a2 commands. That PR includes five synthetic CSV/profile/expected-output
triples and a detailed profile reference. In a checkout containing those changes:

```bash
bankparser parse examples/csv-profiles/euro-split.csv --csv-profile examples/csv-profiles/euro-split.profile.json
```

```python
from bankparser import load_csv_profile, parse

profile = load_csv_profile("examples/csv-profiles/euro-split.profile.json")
result = parse("examples/csv-profiles/euro-split.csv", csv_profile=profile)
assert [str(tx.amount) for tx in result.transactions] == ["-1234.50", "10.25"]
```

Start from a synthetic profile and explicitly map each source header to its
canonical field. Record its date role, monetary convention, encoding, header
position and account/currency constraints. A configured default currency is
caller-supplied context; it does not prove the export supplied a currency.
Profiles are data, not executable parser plugins. Review and version a profile
when the exporter changes; keep independent expectations for both versions.

For repeatable evidence checking, [PR #5](https://github.com/ankurmalik04/-bank-txn-reader/pull/5)
proposes a conformance runner and frozen expectation manifests. Freeze answers
from the source before using the parser to compare them. Retain permission,
independent-review and held-out declarations; neither a profile nor successful
synthetic examples certifies a bank. See the [evidence matrix](profile-evidence.md)
and [sample intake plan](conformance-plan.md).
