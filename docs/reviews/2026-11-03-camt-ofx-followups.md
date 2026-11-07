# CAMT currency multiplicity and OFX empty-result provenance

Implemented 3 November 2026 against PR #24 head
`2b875f57b432c071cda8fec5341246247a8d52df`. The initial combined fix is retained
on local branch `fix/review-20261103-camt-ofx` at `8e4e3f6`.

For the authorized PR updates, the fixes are split at their owning stack stages:
CAMT runtime/tests in #13 (`702fe5b`), OFX runtime/adapter tests in #20 (`c00abde`),
and collected-comparison/CLI tests in #22 (`c59aca1`). Documentation is in #24.
Each predecessor is merged into its dependent branch without rewriting any
original published commit. Comparison tests using collect_errors are introduced
with #22, where that API first exists.

CAMT now rejects repeated direct statement account currency elements with
`AMBIGUOUS_CAMT_ACCOUNT` at `Stmt/Acct/Ccy`, before backend financial extraction.
Identical, contradictory, blank and malformed duplicates are rejected for both
booked and empty statements. Existing single/missing-currency semantics remain.

The alternative OFX adapter preserves valid empty statements and adds
`OFX_BACKEND_UNVERIFIED` when source account, currency or closing balance lacks
backend corroboration. The warning lists the specific source-only fields and
preserves source warnings. Both absent summaries and partial/empty summaries
are covered; supplied conflicting backend fields still cause rejection. Zero
balances remain distinct from missing balances. The code is included in the
redacted diagnostic registry.

Comparison already includes warnings, so the new warning produces differences
against default OFX, even with matching financial values. Both selected parsers
can still succeed: collected reports retain `complete=true`, report
`matches=false`, and CLI `--fail-on-diff` exits 4. No public schema or execution
completeness semantics were changed. Compatibility documentation describes
partial corroboration, source-only metadata and shared source-validation limits.

Validation in the existing macOS/Python 3.14 environment:

- 42 additional regressions; 33 fail against the original source before the fix.
- Full suite: **1,277 passed**, **96.84% branch-aware coverage**.
- Ruff passes across source, tests, corpus generator and scripts.
- Strict mypy passes on 45 source files.
- All 48 independently authored corpus artifacts remain unchanged and pass.
- Existing upstream OFX deprecations remain (284 warnings in the expanded suite).

Final stack logs: `/private/tmp/bankparser-20261103-pr13.log` through
`/private/tmp/bankparser-20261103-pr24.log`. Every updated intermediate head passed
its full branch-coverage suite: 1,082 / 1,098 / 1,133 / 1,139 / 1,146 / 1,165 /
1,174 / 1,235 / 1,257 / 1,277 / 1,277 / 1,277 tests respectively.
The original combined-fix full-suite log and JUnit report remain at
`/private/tmp/bankparser-20261103-full.log` and
`/private/tmp/bankparser-20261103-tests.xml`; they predate the split-test follow-up.
Before-fix regression log: `/private/tmp/bankparser-20261103-before.log`.
The final three boundary cases were added after the before-fix run.

The authorized update targets the existing twelve PR branches with an atomic,
non-force push. PR descriptions must reflect their updated heads and validation;
PR bases and draft states remain unchanged. No merge into main, release tag or
publication is part of this update. Hosted CI on the new heads is still required
before integration. The original development checkout's existing changes were
not overlaid with the PR stack.
