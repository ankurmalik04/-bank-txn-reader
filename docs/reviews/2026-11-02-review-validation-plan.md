# Review validation and grouped fix plan — 2 November 2026

## Scope and evidence

The supplied review is substantially correct. Validate and implement against the
completed PR stack, rather than the older development checkout.

- Development workspace: `/Users/ankur/code/BankParser`, branch
  `alpha-correctness`, committed HEAD `30b844e`, with substantial pre-existing
  tracked and untracked work. It predates several fixes described in the review.
- Verified later checkout: `/private/tmp/bankparser-pr16-17-followup`, clean
  before validation, HEAD `77cc779d883cc7d7111c66b43e8b27cf89c15ef3`.
  This contains the account-path fix, authoritative input-limit fix and six
  pre-refactor assessment snapshots.
- Full suite on that checkout, using the existing development environment and
  `PYTHONPATH=src`: **1,124 passed, 264 warnings, 96.51% branch-aware coverage**.
  The focused existing suite also passed 382 tests.
- Thirteen independent reproduction probes passed in
  `/private/tmp/test_bankparser_review_validation_20261102.py`. These probes
  assert that the gaps are observable, so passing probes demonstrate existing
  problems; they are not regression tests asserting the desired fixed behavior.
- No runtime code was changed. The temporary probes use controlled backend
  outputs to establish missing adapter guards, not to claim that upstream
  libraries naturally produce every tested corruption.

This verifies local source and execution. It does not independently recheck
current GitHub PR states, CI/platform/audit jobs, or establish a merge recommendation
for uninspected later commits.

## Validated findings

| Concern | Result and qualification |
| --- | --- |
| Previous CAMT account-path finding | Fixed in the later checkout: `Acct` participates in `_validate_financial_paths`; conflicting extension accounts have regression coverage in `test_camt_financial_paths.py`. |
| Previous input-limit finding | Fixed: parsing and comparison pass `api.MAX_INPUT_BYTES` explicitly to `load_input`; override and boundary tests pass. |
| Previous assessment snapshot finding | Fixed: six complete serialized assessments, including fingerprints and reason order, are tested against the committed snapshot. |
| Optional OFX currency | Confirmed in `ofx/bankstatementparser.py:248`: `_currency('ßP')` returns `SSP`, which passes `is_currency_code`. The same defect exists in `mt940/bankstatementparser.py:254`. Overlong codes are a different case: they remain invalid for canonical validation; Unicode expansion can erase evidence of malformed source text. End-to-end acceptance of a malformed real export depends on upstream behavior. |
| Alternative OFX source guards | Confirmed in `ofx/bankstatementparser.py:52`: no `read_source()` call, only limited scope/amount syntax/count checks. Controlled backend output with altered IDs, offsetting amount changes, or a conflicting statement/transaction currency is accepted. Duplicate FITIDs, corrections and pending markup rejected by the default source reader also reach and pass the alternative adapter when its backend returns ordinary records. |
| MT940 ordered alignment | Confirmed for both adapters. The source reader intentionally leaves monetary values to the backend. WoLpH accepts reordered output. Alternative MT940 can combine one row's source booking date/reference with another row's backend amount/value date because enrichment happens by index before any financial alignment. Equal transaction counts and unchanged totals do not detect this. |
| Comparison partial failures | Confirmed in `comparison.py:78`: a failure aborts the loop; later implementations are not attempted and prior successes are not returned. This is a capability gap in the current API contract. |
| Backend error disclosure | Confirmed: third-party exception text is interpolated in CAMT, CSV, alternative OFX and both MT940 adapters. A WoLpH exception containing a private marker reaches ordinary CLI text and JSON errors. Default `ofxparse` already sanitizes backend exceptions. Explicit redacted output already removes these messages. |
| Production/held-out evidence | Confirmed by `docs/compatibility.md` and `docs/conformance-plan.md`: 51 demonstration transactions, no established production cohort, second-review sign-off or held-out coverage. Existing conformance tooling should be reused. |
| OFX deprecations | Reproduced: all 264 full-suite warnings come from the four deprecated BeautifulSoup `findAll` calls used by `ofxparse`. No compatible upstream upgrade was evaluated in this task. |
| Release alignment | A follow-up checklist, not a demonstrated defect. The later checkout has version `0.5.0a2` and an Unreleased changelog. Select the next release version after the final merged scope is known. |

## Ordered commit plan

Sizes are relative implementation scope, not delivery guarantees. Each code
commit includes its regression tests and any new diagnostic-code integration.

| Order | Priority | Proposed commit and grouped scope | Size / dependency |
| --- | --- | --- | --- |
| 1 | P1 | **Reject malformed currencies before normalization in OFX and MT940.** Fix both optional `_currency` helpers together using `is_currency_code`; audit WoLpH and MT940 source currency extraction for equivalent normalization paths. | Small; first quick fix. |
| 2 | P2, do early | **Sanitize third-party parser failures across adapters.** Cover CAMT, CSV, alternative OFX and both MT940 adapters in one consistent change; retain exception chaining and align with the already-safe default OFX behavior. | Small–medium; independent of 1, can land immediately after it. |
| 3 | P1 | **Enforce common OFX source and financial guards.** Route alternative OFX through `read_source`, then check backend account, currency, closing balance and ordered transaction IDs/amounts against independently read source facts. | Medium; after 1. |
| 4 | P1 follow-up | **Validate ordered MT940 financial correspondence before source enrichment.** Extend shared source evidence and use one alignment policy in both adapters. This raises the review's P2 scheduling because misattached financial records are directly reproducible. | Medium; after 1; separate from OFX to keep format rules reviewable. |
| 5 | P2 | **Report comparison outcomes per implementation.** Implement report/API/CLI/serialization/privacy behavior together, including documentation and compatibility tests. | Medium; after core integrity fixes and error sanitization. |
| 6 | P2, start intake alongside code work | **Add independently reviewed exporter conformance evidence.** Reuse existing schemas/runner, freeze expectations and held-out inputs, record permissions and reviewer evidence, then update bounded compatibility claims. | External evidence work; no substitute code-only fix. Commit permitted evidence by exporter profile. |
| 7 | P3 | **Update OFX dependency when a compatible remedy is verified.** Evaluate upstream release or a narrowly scoped alternative; run source guards, concurrency, encoding and all installation/audit checks. | Conditional; separate dependency commit. |
| 8 | P3, final | **Prepare the next release.** Align version, changelog, install examples, compatibility limitations and distribution checks against the exact final tree. | Small; after chosen release commits. |

The fast groupings are commits 1 and 2: each fixes one repeated concern across
formats. Keep them separate for independent review and rollback. Keep OFX and
MT940 alignment separate because their identifiers, sign rules and backend
field availability differ. Keep comparison API work separate from correctness
patches; it changes public report and CLI behavior.

## Acceptance criteria by commit

### 1. Currency normalization

- Reject `ßP`, full-width text, non-letter, short and overlong nonblank codes
  before uppercase conversion; accept lowercase ASCII codes and preserve the
  existing distinction between missing values and invalid nonblank values.
- Exercise account/summary and per-record currency paths in both optional
  adapters, including nullable backend scalars.
- Source/backend currency disagreement belongs to commits 3 and 4; syntax
  validation alone cannot detect two different well-formed codes.
- Preserve the existing `INVALID_CURRENCY` diagnostic contract, with useful
  format/field/location context and safe redacted serialization.

### 2. Backend exception privacy

- Use fixed backend-failure messages; preserve the original exception as
  `__cause__`. Retain intentional structured BankParser errors where applicable.
- Assert absence of deliberately sensitive account, narrative and path markers
  from default CLI text and JSON output, and retain redacted-output coverage.
- Audit adapter-authored `{value!r}` errors separately within this change:
  sanitizing only `{exc}` leaves other input-derived values in error messages.
  Scope any remaining deliberate value-bearing validation diagnostics explicitly.
- If new static codes are introduced, update diagnostics, trusted-code
  serialization, documentation and tests together. Do not promise that successful
  parse output or its upstream warning messages is automatically redacted.

### 3. OFX source parity

- Reject duplicate IDs, corrections, pending activity, misplaced financial
  fields and unsupported scopes before invoking either backend.
- Reject count changes, reorderings, altered IDs, offsetting amount changes,
  currency/account disagreement and closing-balance disagreement.
- Missing source values must remain missing; no invented opening balance or
  backend placeholder may silently become a sourced financial fact.
- Keep backend-specific descriptions and existing public raw fields compatible
  unless a deliberate documented contract change is needed. Reusing the source
  reader does not require replacing all existing canonical output wholesale.
- Verify dependency behavior: the alternative-only install must be able to use
  the hardened source reader for XML as well as SGML. Declare any newly direct
  hardened-XML dependency explicitly and test that installation profile.

### 4. MT940 source alignment

- Capture exact Decimal amount, debit/credit/reversal mark, value date, optional
  booking date, references, source line and available statement currency.
  Currency comes from available statement evidence; the optional funds code is
  not a complete three-letter transaction currency.
- Check ordered backend financial tuples before adding source dates/references;
  compare backend references wherever actually exposed. Validate available
  account/balance/currency evidence consistently.
- Test normal and reversal signs, year boundaries, missing balances/currency,
  equal totals with reordered or offsetting amounts, and mismatched references.
- Preserve legitimate repeated transactions. MT940 references are not guaranteed
  unique, and a backend that omits references cannot independently prove identity
  for otherwise identical tuples. Document that limit instead of inventing IDs
  or claiming index-based enrichment independently verifies identity.
- Avoid unintentionally publishing new source-evidence fields through `raw`.

### 5. Partial comparison outcomes

- Record each implementation's success or safe failure code; successful outcomes
  include transaction count and validation status. Attempt every selected parser
  for expected parser failures; input/configuration errors remain explicit.
- Keep a single bounded input snapshot and deterministic selection/order.
- Compare canonical fields among successful outputs when at least two exist.
  Define incomplete/all-failed states explicitly: one success must not be
  reported as agreement, and zero successes must not masquerade as a match.
- Preserve `compare_results` for callers already holding successful results.
  Choose and document backward compatibility for `compare` before changing its
  currently fail-fast contract, including whether collection is opt-in.
- Define CLI exits for partial and total failure alongside existing
  `--fail-on-diff`; do not silently return successful completion for incomplete
  comparisons. Test full/canonical/redacted projections together.

## Verification and release gate

For each commit, add focused tests that fail on the validated baseline and pass
after the fix. After integrating the code changes, run the full branch-coverage
suite, Ruff, strict mypy, corpus/conformance checks and affected installation
profiles. Include distribution/audit checks for dependency changes. Treat the
current 1,124-test result as a baseline, not evidence that the new guard behavior
is covered. No fixes, commits, pushes, PR changes or release actions are part of
this validation-and-planning task.
