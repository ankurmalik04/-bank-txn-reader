# Review fix PR stack — 2 November 2026

All seven PRs remain drafts, based on existing PR #17 at `77cc779`. Each original
fix commit is preserved. Follow-up commit `78202dd` aligns the contradictory
MT940 currency regression with the sanitized backend error at #19, and checks
that the original diagnostic remains available through the chained exception.
The fix is carried through #20–#24 by merging each updated predecessor into its
dependent branch. No force push or history rewrite is required.

| PR | Scope | Original commit | Updated integration commit |
| --- | --- | --- | --- |
| [#18](https://github.com/ankurmalik04/-bank-txn-reader/pull/18) | Currency syntax | `e014b72` | Unchanged |
| [#19](https://github.com/ankurmalik04/-bank-txn-reader/pull/19) | Backend error privacy and matching regression assertion | `ca44492` | `78202dd` |
| [#20](https://github.com/ankurmalik04/-bank-txn-reader/pull/20) | Shared OFX source guards | `a90b214` | `244e61d` |
| [#21](https://github.com/ankurmalik04/-bank-txn-reader/pull/21) | MT940 ordered financial alignment | `43a6ecc` | `9ed92ba` |
| [#22](https://github.com/ankurmalik04/-bank-txn-reader/pull/22) | Comparison outcomes | `4b1165f` | `699b53a` |
| [#23](https://github.com/ankurmalik04/-bank-txn-reader/pull/23) | Assessment snapshot packaging | `0d4547f` | `b8b1c7e` |
| [#24](https://github.com/ankurmalik04/-bank-txn-reader/pull/24) | Documentation and handoff | `c47c0a8` | `3f6b875`, followed by the OFX clarification and this handoff |

#24 now distinguishes the explicit OFX adapter's released 0.5.0a2 limitation
from the shared source guards in the unreleased implementation. This does not
extend production/conformance claims.

## Validation

The original #19 and #20 test workflows failed on the stale error-message
assertion across all seven full-suite jobs. The original #18 and #21–#24 test
and runtime-audit workflows passed. The later passing heads did not make #19 or
#20 suitable for an intermediate merge.

Full local branch-coverage suites passed at every repaired code head:

| PR head | Tests passed | Coverage |
| --- | --- | --- |
| #19 | 1,152 | 96.77% |
| #20 | 1,198 | 96.82% |
| #21 | 1,220 | 96.74% |
| #22 | 1,235 | 96.78% |
| #23 | 1,235 | 96.78% |
| #24 integrated tree | 1,235 | 96.78% |

Runs used macOS/Python 3.14 and retained 264 existing upstream OFX warnings.
Logs are under `/private/tmp/bankparser-review-comments-20261102`. Local results
do not substitute for hosted CI on each newly published head.
Ruff, strict mypy for all 45 source files, and all 48 corpus artifact checks
also pass on the final documentation tree.

## Merge gate

Keep the PRs unmerged during repair. Require fresh successful test and runtime
dependency audit workflows on each updated head. Preserve stack order and
satisfy #13–#17 dependencies first. As each predecessor lands, update/retarget
the next PR against current `main` and wait for its required CI. Check `main`'s
push workflow before proceeding. Never accept a known-red intermediate merge
on the assumption that a later PR will repair it.

No main-branch commits, repository protection settings, release tags or
publication actions are part of this correction.
