# Run sample conformance checks

The source-distribution tool `scripts/check_conformance.py` compares frozen,
independently reviewed expectations with canonical parser output. It reuses the
ordered field/count/hash workflow from the earlier CAMT demo review, with strict
input validation and reusable versioned contracts for all four supported formats.
It does not create expected answers, change parser rules, split statements,
certify exporters or authenticate declarations. It adds no runtime dependencies
and is not a new public parsing API or installed console command.

## Try the synthetic examples

From a source checkout, with the base runtime installed:

```sh
PYTHONPATH=src python scripts/check_conformance.py examples/conformance/native-csv.manifest.json
PYTHONPATH=src python scripts/check_conformance.py examples/conformance/mt940.manifest.json --json /tmp/mt940-conformance.json --markdown /tmp/mt940-conformance.md
```

In an unpacked source distribution with its runtime installed, omit PYTHONPATH.
The CAMT and OFX examples require their respective extras:

```sh
PYTHONPATH=src python scripts/check_conformance.py examples/conformance/camt053.manifest.json
PYTHONPATH=src python scripts/check_conformance.py examples/conformance/ofx.manifest.json
```

All example expectations copy only account, statement and transaction fields
from the existing independently authored corpus goldens, adding version headers.
No parser was run to author them. See [corpus provenance](../corpus/PROVENANCE.md).
They remain synthetic development evidence: no production exports, second review
or untouched held-out evidence is asserted. The historical bank demo originals,
expected answers and reports remain unchanged and private. Their previous wrapper
format is not automatically accepted; manually review a conversion into v1 while
retaining original hashes and labeling any transformations.

## Prepare private evidence

Follow the [intake and review plan](conformance-plan.md). Keep private originals,
permissions, manifests, answers and generated reports outside public Git and
release artifacts. JSON and Markdown reports contain canonical financial data,
identifiers and reviewer/profile declarations; they are not redacted. Only the
independently invented examples belong in public source. Hashes identify bytes,
not authenticity or permission.

1. Select one exact exporter profile and record its version, format version,
   encoding, account type, currency, locale, date/amount meanings and additional
   exporter settings. `implementation` selects one existing parser; `csv_options`
   supports the CsvOptions fields, including explicit mappings, header selection,
   currency fallback/constraints and encoding (see [CSV profiles](csv-profiles.md)). Settings are recorded
   evidence, not executable rules; only the declared CsvOptions configure parsing.
2. Independently establish every account/statement/transaction field directly
   from permitted source evidence. Use the complete shape in an example
   `.expected.json`, including nulls for genuinely absent canonical values.
   Amounts are plain exact decimal strings, dates are YYYY-MM-DD. Keep the exact
   transaction order and every legitimate repeat. Do not copy parser output into
   the oracle. Record ambiguities rather than inventing financial facts.
3. Record permission, author, method, independent reviewer (or null), evidence
   kind (`synthetic`, `demo`, `production`), cohort (`development`, `held-out`) and
   `held_out_untouched`. Review declarations are recorded, not verified. A reviewer
   cannot equal the author. If a held-out answer drives a fix, reclassify that
   sample as development and obtain a new untouched sample.
4. Freeze source and expectation files. Record the SHA-256 of each exact file's
   bytes in the manifest. Source/expected paths resolve relative to the manifest;
   absolute paths and references outside the checkout are supported for private
   intake. Never publish a private manifest just because the report omits paths.
5. Run the manifest. Changed hashes stop that sample before parsing. A sample
   error does not suppress later samples. Invalid manifest configuration aborts
   before any parsing. Files are bounded to the runtime's 5 MiB input limit,
   including manifest and expectations; JSON nesting is limited to 64 levels. Use
   separate manifests for larger cohorts.

The runner reads one source snapshot for hashing and parsing. Expectation files
are read once and never rewritten. It does not guess identities, rematch shifted
transactions, deduplicate repeats or silently transform multi-statement input.
Split scopes only as an independently recorded transformation and hash the
actual derived input. Count deltas indicate how many transactions differ, not
which economic records are missing/extra when earlier insertions shift ordinals.

## Versioned file contracts

All three tooling schema versions are the string `"1"`; canonical parse schema
remains `"1.1"`. JSON Schemas use Draft 2020-12:

- [Manifest schema](schemas/conformance-manifest-v1.schema.json)
- [Expectation schema](schemas/conformance-expectation-v1.schema.json)
- [Report schema](schemas/conformance-report-v1.schema.json)

The runner validates input using the standard library; installing a JSON Schema
library is unnecessary. It rejects unknown/missing keys, duplicate JSON keys,
invalid dates or amount types, nonfinite JSON numbers, duplicate sample IDs,
invalid options/digests and contradictory evidence declarations. JSON Schema
editors can check structural shape; uniqueness across sample IDs, reviewer/author
inequality, legal CSV-option combinations and policy-path eligibility are semantic
checks enforced by the runner. The manifest's `profile.settings.extra` is a
record-only JSON object for additional exporter settings.

A frozen expectation contains `expectation_schema_version`,
`canonical_schema_version`, `account`, `statement` and `transactions`. It compares
all canonical fields in that scope; raw backend data and validation messages are
excluded. Parser warnings and check codes/statuses are recorded separately.
Expected failure profiles are not a v1 contract: parser rejection is a reported
error, not a conformance pass. Use focused negative regression tests for those.

Each report separates deterministic `facts` from volatile `execution` time,
Python/platform information and tool package version. Facts include the exact
manifest/source/expectation hashes, profile, backend/parser versions, counts,
per-currency booked totals, differences, explicit checks, evidence declarations
and summary. Facts reproduce under identical inputs and parser versions; parser
version changes or changed manifest bytes deliberately change provenance.

## Interpret findings

Financial differences include account and statement scope, dates, balances,
transaction counts, booked amounts, currencies and transaction IDs. Description,
reference and counterparty differences are metadata. All unexplained differences
fail the sample. Monetary values compare numerically without rounding; reports
retain the original decimal strings and preserve null/empty/literal text meanings.
A difference includes explicit expected/actual presence flags. Ordered fields
remain checked even if count and signed totals agree, so offsetting wrong amounts
cannot hide behind global reconciliation. Totals never add different currencies;
missing currency stays missing. Expected and actual balances are checked separately
when prerequisites exist. Parser validation failures fail conformance; warnings
remain explicitly skipped/incomplete internal checks rather than invented passes.

A sample can declare exact metadata-only exceptions, for example:

```json
"policy_differences": [
  {"path": "transactions[0].reference", "reason": "Documented canonical reference priority"}
]
```

The path must exist in the expected metadata and include a nonblank reason.
Financial or unknown-path exceptions are rejected before parsing. Exceptions
never erase or rewrite the oracle or findings: actual disagreements remain in
the report under category `policy`, with both original values and the reason.
No wildcards, monetary tolerances or automatic oracle updates are supported.

A `passed` sample means the checked output matched the supplied oracle within
listed metadata policies and had no failed financial checks. It does not mean
all evidence prerequisites passed. Production evidence, second review and
held-out use each have explicit passed/skipped declaration checks; synthetic
examples can conform while all three remain skipped. The report always says
certification was not assessed. This runner alone does not complete the plan's
3–5 profile certification/evidence requirements.

## Output and exit status

Without `--json`, JSON goes to stdout. `--json FILE` and `--markdown FILE` create
new report files; existing outputs, symlinks and identical output paths are
rejected. Files are created with owner-only permissions on POSIX (`0600`, subject
to the umask); Windows uses inherited filesystem ACLs. Shell redirection of stdout
uses the shell's file permissions. Inputs/expectations cannot be overwritten.
If creating a later output fails, an earlier successfully created output can
remain; the tool exits 2.

| Exit | Meaning |
| --- | --- |
| 0 | All samples conformed within explicit metadata policies; evidence checks may still be skipped. |
| 1 | At least one conformance/financial failure and no sample errors. |
| 2 | Manifest/output error or at least one sample hash/input/parser error. |

Sample-level errors are in the report; a malformed manifest or output failure is
a structured error on stderr. Argument/usage errors remain argparse text.
Sensitive backend exception messages and filenames are not copied into sample
errors; codes and locations are recorded. Review reports privately before sharing.
