# Review fixes — 2 November 2026

## Branch and scope

Implemented on `fix/review-integrity-20261102` in
`/private/tmp/bankparser-pr16-17-followup`, based on the validated completed
PR-stack commit `77cc779d883cc7d7111c66b43e8b27cf89c15ef3`.
The original `alpha-correctness` working checkout and its pre-existing changes
were preserved. This branch includes the prior stack as ancestry; its fix-only
review range is `77cc779..fix/review-integrity-20261102`.

| Commit | Grouped concern |
| --- | --- |
| `e014b72` | Pre-normalization currency checks for optional OFX/MT940 and WoLpH mapping. |
| `ca44492` | Sanitized backend failures and invalid scalar diagnostics across adapters, retaining exception chaining. |
| `a90b214` | Shared OFX source guards and ordered financial alignment for the alternative backend; explicit hardened XML dependency. |
| `43a6ecc` | MT940 ordered amounts, dates, reference evidence and account/final-balance checks across both adapters, before source enrichment. |
| `4b1165f` | Opt-in comparison outcome reports, CLI exit semantics, privacy projections and API documentation. |
| `0d4547f` | Include assessment snapshot JSON in source archives and require it in distribution checks. |

The initial documentation commit records the new behavior, evidence and remaining
work. At that validation stage, no push, PR change, merge, tag or publication had
been performed. Subsequent PR creation and the intermediate-CI correction are
recorded in [the PR stack handoff](2026-11-02-review-pr-stack.md).

## Behavior and compatibility

- Both optional currency helpers reject malformed original text before uppercasing.
  Missing scalars and valid lowercase ASCII codes retain their existing meaning.
- Both OFX adapters share source rejection rules. Alternative output must agree
  with independently read financial evidence. Empty statements retain their
  source account, balances and warnings; opening balances are not invented.
- Both MT940 adapters reject reordered/altered financial records. The alternative
  adapter verifies backend reference evidence before adding source-only metadata.
  Legitimate repeated transactions remain distinct; identical exposed tuples and
  references cannot independently establish unique economic identity.
- `compare(..., collect_errors=True)` returns `ComparisonRunReport` with ordered
  `ComparisonOutcome` records. CLI `--collect-errors` emits incomplete reports to
  stdout and exits 2. The successful subset is compared when at least two exist;
  incomplete runs never claim a match. Default calls retain the existing
  fail-fast behavior and serialized shape. Input/configuration/programming errors
  are not silently collected as ordinary backend outcomes.
- Default third-party failure messages no longer echo upstream exception text.
  Chained exceptions remain available for Python debugging. Full successful
  output and deliberate source diagnostics are not automatically redacted.

## Verification

- Existing baseline: 1,124 passed, 96.51% branch-aware coverage.
- Implemented tree: **1,235 passed, 96.78% branch-aware coverage**, 264 existing
  upstream OFX deprecation warnings. New regression tests were run against the
  pre-fix code to establish that the gaps were observable.
- Full 1,235-test suite and 96.78% coverage also passed from the unpacked source
  archive with freshly resolved runtime dependencies. This includes mt-940 5.1.3,
  while the original development environment exercises 5.1.1.
- Ruff, strict mypy (45 source files), and all 48 independently authored corpus
  artifact checks pass. All four synthetic conformance example commands succeed;
  this adds no production or independent second-review evidence.
- Built wheel and source archive pass distribution content/metadata/checksum
  validation. Packaging verification found that the pre-existing assessment
  snapshot JSON was absent from the source archive; its packaging is now fixed.
- **12 clean installation checks pass**: wheel and source archive, each with
  base, csv, ofx, camt, alternative and all. Each resolves dependencies offline
  from freshly downloaded wheels, passes `pip check` and the isolated installed
  runtime/CLI smoke checks. No audit/test/build tools were installed into those
  runtime environments.
- The exact installed all-profile dependency closure contains 18 runtime packages.
  Its pinned inventory covers the six profile subsets. Separate pip-audit 2.10.1
  checks against PyPI and OSV both report no known vulnerabilities. These are
  point-in-time advisory results, not a general safety guarantee.

Artifacts, logs, reports and runtime inventories are retained under
`/private/tmp/bankparser-review-20261102-artifacts` and
`/private/tmp/bankparser-review-20261102-installs`. The build log is
`/private/tmp/bankparser-review-20261102-build.log`.

## Remaining work and release handling

1. **Production evidence:** choose the first exporter profiles, obtain permitted
   development/held-out inputs, identify an independent reviewer and freeze
   source-derived expectations using the existing conformance tooling. The
   earlier 51 demonstration transactions remain the evidence limit. No missing
   production exports, permissions or reviewer sign-off were fabricated.
2. **OFX warnings:** [PyPI](https://pypi.org/project/ofxparse/#history) still lists
   0.21 as the latest release. There is no published upgrade to test for these
   deprecations. Keep the pin and visible warnings until a compatible remedy is
   available; no dependency fork or monkeypatch was introduced.
3. **Release:** the changelog records these changes as Unreleased. The package
   version and existing download instructions remain 0.5.0a2, matching the
   baseline release. Locally built artifacts with that version are validation
   artifacts and must not replace published 0.5.0a2 files. After the PR stack and
   fixes are merged, choose the next version, update version/changelog/download
   references together, rebuild and run release CI on that exact versioned tree.
   The original PR heads subsequently passed cross-platform/multi-Python CI at
   #18 and #21–#24; #19–#20 required the assertion correction described in the PR
   stack handoff. Updated heads require their own CI results. Publication remains
   outstanding.

The code fixes and packaging correction are complete locally. Production evidence,
an unavailable upstream upgrade, and the post-merge release remain follow-ups.
