# Bank/exporter sample conformance plan

Saved 21 October 2026; evidence status updated 24 October 2026. Status: incomplete;
three official bank demos have source-based comparisons covering 51 transactions,
but no production-export cohort, independent second review or held-out samples.
See the bounded results and exclusions in [compatibility.md](compatibility.md).
Maintainer: ankurmalik04. The first alpha is published;
private security reporting and notifications are complete per maintainer confirmation.

## Goal and first cohort

Establish bounded evidence for 3–5 versioned bank/exporter profiles that actual
users need. A profile identifies exporter, format/version, export settings,
encoding, account type, currency, locale and date/amount conventions. Coverage
applies to those settings and evidence, rather than every export from a bank.

1. Ask prospective users which imports block their workflow. Rank by actual
   demand, ability to supply permitted examples and fit with existing parsers.
2. Start with one CSV profile and one OFX/QFX or MT940 profile. Add CAMT and
   further profiles only when relevant samples and an independent reviewer exist.
   Record selected names and priority after intake; no banks are assumed here.
3. Target at least three distinct exports per profile: two for development and
   one held out before implementation. Prefer different periods with income,
   payments, refunds/reversals, repeated legitimate charges and no-activity cases
   where the exporter supports them. Record gaps rather than manufacture coverage.

## Intake and permission

Use an agreed private transfer route. Public issues accept independently invented
reproducers only; do not attach customer statements or financial identifiers.
Before collecting a file, record the owner's permission, allowed uses, access,
retention/deletion date and whether any transformed fixture may be redistributed.
Never assume permission to inspect a file permits public redistribution.

Maintain a private intake register with sample ID, profile/settings, source date,
SHA-256, format version, permission record, storage location, reviewer and cohort
(development or held out). Keep originals outside Git and release artifacts with
access limited to authorized reviewers. Hashes identify bytes, not authenticity.
Review sanitized outputs for account identifiers, names, references, free text
and metadata. If redistribution is not explicitly permitted, publish only
aggregate results and independently invented regression inputs. Track how
sanitization affects the evidence; invented fixtures are synthetic evidence.

## Independent expectations

Before running parser comparison, a reviewer establishes expected account scope,
statement dates, balances/currencies, transaction count/order and every available
canonical transaction field directly from the export and any permitted independent
statement evidence. Record absence, ambiguity and unsupported meanings explicitly.
Use exact decimal amounts and distinguish booking/value dates and booked/foreign
amounts. An independent second review checks count, signs, currency, account
assignment and balances. Parser output must not generate the expected answers.

Record who checked each expectation, how, and unresolved discrepancies. Where
independent statement evidence is unavailable, describe that limitation; a second
parser or a balanced total alone does not establish completeness.

## Execute and report

For each sample record package, backend, profile and schema versions, options,
platform, input hash, expected/actual counts, missing/extra records, wrong
account/currency/sign events, field mismatches, warnings and failures. Preserve
legitimate repeated transactions; align using trustworthy scoped identities or
review ambiguous matches manually. Check count and booked-amount conservation
and balances where prerequisites exist. Report skipped checks explicitly.

Develop profile rules and synthetic regression cases against development samples.
Reject unknown or ambiguous settings with documented errors. Then run the frozen
held-out samples without tuning against their answers. If a held-out case drives
a fix, move it into development evidence and obtain a new held-out sample before
claiming held-out success.

## Completion criteria and deliverables

- 3–5 profile records with permission, export settings and documented boundaries.
- Independently reviewed expectations and at least one untouched held-out export
  per profile; missing evidence is labeled incomplete.
- Zero unexplained missing/extra transactions or wrong account/currency/sign
  events on accepted samples. Other differences are resolved or explicitly
  excluded from the support contract; unsupported cases have documented errors.
- A dated conformance report with sample counts, versions, findings and evidence
  limits; public material contains only permitted non-sensitive information.
- Compatibility documentation updated only for demonstrated profile boundaries.
  Evidence includes synthetic regression cases where allowed and useful.

## Next actions

1. Maintainer identifies prospective users and selects the first two exporters.
   Outreach and data transfer require a separately agreed recipient and route.
2. Agree permission and retention terms; create the private intake register and
   collect the development/held-out sample cohort.
3. Assign expectation author and independent reviewer; freeze expected results.
4. Run the checks, triage gaps and implement the first explicit profile.
5. Review held-out evidence and publish a bounded conformance report before
   expanding the profile set. Schedule is driven by sample/reviewer availability.
