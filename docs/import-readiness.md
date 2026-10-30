# Assess destination import readiness

Parsing extracts a canonical statement; validation checks its internal financial
consistency; readiness applies a destination's requirements. They are separate
contracts. `assess_import` returns a new report and never changes the ParseResult,
fills its fields, removes movements, writes to a ledger or authenticates a file.
Canonical parse schema remains 1.1. Policy/assessment files have separate v1
schemas and no new runtime dependency.

```python
from bankparser import ImportPolicy, assess_import, parse

parsed = parse("corpus/csv/basic_valid.csv")
assessment = assess_import(parsed, ImportPolicy(id="my-import", version="1"))
print(parsed.validation.status)  # warning: balances/value dates are unavailable
print(assessment.status)         # ready: this destination does not require them
```

Readiness assumes a successfully parsed schema-1.1 result in a supported format.
A parser exception is still an error, not a readiness outcome. Matching balances
or a ready assessment proves neither authenticity nor completeness, certified
exporter support, correct destination ownership or freedom from cross-file repeats.

## Outcomes and reasons

| Status | Meaning |
| --- | --- |
| `ready` | No unmet blocking/review requirements under this explicit policy/context. |
| `review` | At least one review reason and no blocker. |
| `not-ready` | At least one blocker, regardless of other reviews. |

Each reason contains code, severity (`review` or `block`), path, zero-based
transaction_indices, a static explanation and optional source_code for a related
validation/warning/candidate kind. Reasons do not require parsing English messages.
`transactions[].field` applies to the listed source-order indices. Empty indices
mean a statement/context-level condition. The report includes the resolved policy,
optional destination, account-origin label, original validation status and freshly
recomputed ValidationResult. It can contain sensitive balances, codes and identity
context; it is not a redacted diagnostic.

Every failed recorded check or failed recomputed canonical invariant **blocks**,
including unknown failed checks. A failed recorded aggregate without individual
failures also blocks. Recomputing catches post-parse data replacement or stale
passed validation, while preserving failed source checks that cannot be recreated.
Invalid recorded statuses or canonical field types are input errors. No policy,
confirmed destination or duplicate review token can override these blockers.
The original ValidationResult, parser warnings and parse/compare behavior remain
unchanged.

## Policy actions and defaults

`ImportPolicy` is immutable and has id/version plus these actions. Each action is
`ignore`, `review` or `block`: ignore permits that condition, review prevents
unattended readiness, block prevents readiness until the condition is resolved.

| Action field | Default | Applied condition |
| --- | --- | --- |
| `booking_date` | block | Missing transaction booking date. |
| `transaction_currency` | block | Missing/blank transaction currency; account currency does not fill it. |
| `account_identity` | review | No source ID/IBAN or permitted confirmed destination account context. |
| `value_date` | ignore | Missing value date, except explicitly exempted formats. |
| `description`, `reference` | ignore | Missing/blank field, assessed separately. |
| `opening_balance`, `closing_balance` | ignore | Missing balance or missing currency for a required balance. |
| `statement_period` | ignore | Missing start or end bound. |
| `duplicate_candidates` | review | An unreviewed candidate within this result. |
| `configured_currency` | review | CSV currency supplied by fallback, from raw provenance or CONFIGURED_CURRENCY warning. |
| `value_date_outside_period` | review | Known settlement date outside source bounds; distinct from missing dates. |
| `other_incomplete_checks` | review | Unknown skipped checks or unexplained recorded warning aggregate. |
| `other_warnings` | review | Parser warnings beyond known field-availability warnings. |
| `empty_activity` | review | No movements to import. |

`allow_destination_account=True` permits caller-confirmed destination context to
satisfy account identity; false requires source identity when the action demands
it. `value_date_exempt_formats=()` can be a tuple of csv/mt940/camt053/ofx. For
example, `value_date="block", value_date_exempt_formats=("ofx",)` permits missing
OFX value dates without exempting actual settlement-date exceptions or failures.

Known skipped validation prerequisites are assessed through these fields, rather
than turning every aggregate warning into a blocker. Missing optional balances,
period bounds or value dates can therefore be acceptable. Known field warnings
and CSV running-balance ambiguity do not create an extra generic review when the
destination does not require that canonical field. OFX response/backend warnings
and other unknown parser warnings use other_warnings. Currency presence is not an
ISO registry check. No balances, dates, currencies or identities are inferred.

Load data-only versioned JSON policies:

```python
from bankparser import load_import_policy

policy = load_import_policy("examples/import-readiness/movements.policy.json")
```

The envelope is `{"policy_schema_version":"1","policy":{...}}`. Unspecified
policy fields use the documented defaults; resolved fields appear in each report.
The loader accepts at most 64 KiB of UTF-8 JSON, rejects duplicate/unknown keys and
invalid actions/types/versions and never executes code. JSON format exemptions
are arrays; direct Python configuration requires an immutable tuple. Example
policies illustrate movements-only versus source-reconciled requirements; they
are synthetic conventions, not recommendations for every accounting destination.

## Destination context without changing source facts

```python
from bankparser import DestinationAccount, assess_import

destination = DestinationAccount(
    id="ledger-cash-gbp",              # the application's ledger id
    currency="GBP",                    # a destination constraint, never a source fill
    mapping_confirmed=True,            # caller's declaration, not library verification
)
assessment = assess_import(parsed, destination=destination)
```

Destination id is an application identifier, so it is not compared to the bank's
account ID. Optional source_account_id/source_iban assert the bank identity
expected for that ledger: a conflict with a known source field always blocks,
even with a permissive policy and confirmed mapping. Comparisons strip outer
whitespace and otherwise use exact identifiers; no fuzzy matching or IBAN
normalization/verification is performed. Known currencies must match destination
currency (three-letter options normalize to uppercase); unknown transaction
currency is never filled from the destination.

An unconfirmed supplied destination always requires review. With missing source
identity, a confirmed allowed context labels account_origin as destination-context;
it does not populate or claim source account fields. Otherwise account_origin is
source when an ID/IBAN exists, or missing. A strict policy can require source
identity by setting allow_destination_account=false and account_identity=block.
Confirmation is a caller declaration, not ownership/identity evidence verified
by this library.

## Review duplicate candidates without losing movements

The assessor groups repeated nonblank transaction IDs and similar canonical
records (booking/value dates, exact numeric amount/currency, description,
reference and counterparty). Different transaction IDs can still yield a similar
record candidate. Equal Decimal scales and signed zero compare numerically;
no fuzzy matching is performed. A repeated bank ID or identical charge is only
a candidate, not proof of duplication. Every transaction remains intact. Groups
can overlap; each unreviewed group is assessed separately. Identical index groups
prefer the transaction-id label.

```python
first = assess_import(parsed)
# After reviewing the actual group and destination requirements:
reviewed = (first.duplicate_candidates[0].fingerprint,)
second = assess_import(parsed, reviewed_duplicates=reviewed)
```

The result_fingerprint hashes a deterministic canonical projection of schema,
format, account, statement and ordered transactions, excluding raw fields,
backend provenance, warnings and recorded validation. Each candidate fingerprint
binds its kind and indices to that entire result fingerprint. A change anywhere
in the canonical result invalidates review tokens. Tokens are not a source-file
hash, authentication, anonymity, proof that review occurred or import-history
state. An identical canonical result can reuse a token even from different bytes.
Caller review is explicitly declared; it does not override failed validation or
other unmet policy requirements. Unknown/stale/duplicate tokens are input errors.

`duplicate_candidates=block` blocks an unreviewed group; explicit valid review
resolves that condition. ignore permits the group while leaving it visible and
unreviewed in the report. There is no automatic deletion, cross-file matching,
database, network lookup or persistent review store. Cross-file duplicate/history
handling remains separate backlog work.

## CLI and serialization

```sh
bankparser assess corpus/csv/basic_valid.csv --policy examples/import-readiness/movements.policy.json --json-errors
bankparser assess statement.csv --destination-account ledger-7 --destination-currency GBP --confirm-account-mapping --json-errors
```

CSV options, --csv-profile, guarded --format csv and --implementation work as in
parse. Destination flags also include --expected-source-account and
--expected-source-iban. Supplying destination sub-options requires a destination
id. Repeat --reviewed-duplicate FINGERPRINT for explicitly reviewed groups.

| Assess exit | Meaning |
| --- | --- |
| 0 | Ready. |
| 5 | Review required. |
| 6 | Not-ready. |
| 2 | Parse, policy, context or token error. |

Completed assessments always emit full JSON on stdout, including exits 5/6,
with empty stderr. Errors emit no assessment stdout; --json-errors uses the
existing structured error object on stderr. Argument/usage errors remain
argparse text unless `--output-policy redacted-diagnostic` is requested; then
only `CLI_USAGE_ERROR` is emitted (as a code-only object with `--json-errors`).
Parse validation exit 3 and comparison mismatch exit 4 are unchanged.
There is no import/ledger write operation.

Python reports use the existing `to_primitive` before json.dumps. The separate
[policy schema](schemas/import-policy-v1.schema.json) and
[assessment schema](schemas/import-assessment-v1.schema.json) use Draft 2020-12.
The [source example](../examples/import-readiness/demo.py) runs on independently
invented corpus data. Reports/context may contain financial identifiers and
amounts; keep private statements and derived reports outside public artifacts.
