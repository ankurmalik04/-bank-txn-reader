# Format and profile evidence

This is a bounded evidence summary for 0.5.0a2 and the explicitly identified
proposed features. It is not a bank compatibility directory. The
[compatibility guide](compatibility.md) specifies the adapter boundaries and
the [sample plan](conformance-plan.md) defines the remaining evidence milestone.

## Released runtime evidence

| Format | Default / install | Evidence in this checkout | Important boundary |
| --- | --- | --- | --- |
| CSV | native / base | Independently authored synthetic amount/date/identity fixtures and malformed-layout regressions | Recognized headers, one account/currency scope; generic Date and running balances remain raw. |
| MT940 | wolph / base | Synthetic balances, reversals, separate dates/references and repeated-scope rejection | One statement; intermediate-balance policy is not established. |
| CAMT.053 | bankstatementparser / camt | Synthetic `.053.001.02` canonical fixtures, source alignment and scope guards | One Stmt; indistinguishable financial identities can be rejected in 0.5.0a2. |
| OFX/QFX | ofxparse / ofx | Synthetic bank/card, encoding and financial-activity regressions | One supported response; unsupported transaction types/corrections fail explicitly. |

CSV and MT940 have optional bankstatementparser implementations; OFX has an
alternative too. Backend agreement is a consistency observation, not independent
proof of source extraction. Consult the compatibility guide before switching.

## Proposed reusable CSV examples

These five examples are in [PR #6](https://github.com/ankurmalik04/-bank-txn-reader/pull/6),
not released 0.5.0a2. Each has invented source data and independently specified
expectations. None is a production exporter certification.

| Synthetic profile | Layout / convention | Evidence status |
| --- | --- | --- |
| mapped-signed | Explicit posting/settlement, account, ID and reference mappings; signed amount | Synthetic source/profile/expected triple. |
| euro-split | Semicolon, third-line header, debit/credit, comma decimals, booking Date | Synthetic source/profile/expected triple. |
| preamble-debit | Fourth-line header, debit-only movements, account and IBAN fields | Synthetic source/profile/expected triple. |
| legacy-tab | cp1252, bounded header search, value Date and configured GBP fallback | Synthetic source/profile/expected triple. |
| unicode-pipe | UTF-8 non-English headers and pipe separator | Synthetic source/profile/expected triple. |

## Evidence still needed

No profile is certified under the sample plan. Production exports, independent
second-review sign-off and untouched held-out samples remain incomplete. Planned
3–5 exporter profiles are an intake target, not support already delivered.

Record exact exporter/version settings, permission, source and expectation
hashes, author/reviewer and development/held-out cohort for each candidate. If a
held-out sample drives a fix, move it into development and obtain a new held-out
sample. Preserve disagreements, missing fields and explicit policy exceptions.
The [proposed runner in PR #5](https://github.com/ankurmalik04/-bank-txn-reader/pull/5)
records these declarations but cannot verify permission or certify their truth.

Release CI checks versions, package contents, clean installation profiles,
checksums and dependencies. Those checks concern a particular commit/artifact;
their existence does not show that a different candidate has passed. PyPI
publication remains deferred. GitHub download installation is documented in the
[README](../README.md); publication is a separate maintainer action.
