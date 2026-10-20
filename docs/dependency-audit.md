# Runtime dependency audit — 9 October 2026

Result: all 18 runtime distributions in the all-extra closure were checked with
pip-audit 2.10.1 against both the PyPI and OSV advisory services. Both the
previously tested version set and a fresh resolution returned zero package
advisories, with no skipped packages, ignored vulnerabilities or automatic fixes.
This is dated evidence for exact versions, not proof that all allowed versions,
platform wheels or native libraries are vulnerability-free.

## Scope and evidence

| Installation | Runtime dependency distributions, excluding BankParser |
| --- | ---: |
| Base MT940/native CSV | 1 |
| OFX | 8 |
| CAMT | 15 |
| Alternative | 15 |
| All | 18 |

Counts come from installed Requires-Dist metadata, recursively evaluating active
Python/platform markers and selected project extras. Unrelated development/audit
packages and inactive upstream extras are excluded. The inventory tool fails
on missing/incompatible installed versions, direct URLs and unsupported nested
extras rather than silently undercounting.

[Evidence directory](audits/2026-10-09-dependencies/) includes the installed
inventory/license-file hashes, per-profile pinned audit inputs and the four
PyPI/OSV JSON reports. Pins reproduce the audit inputs; they are not application
lockfiles or a change to the library's public dependency ranges.
Fresh resolution changed Pydantic/core from 2.13.5/2.46.5 to 2.14.0/2.50.0.
Artifact URLs/hashes for the fresh installation are recorded separately without
local source paths. Licenses were inspected from shipped files, not inferred
solely from PyPI display labels. In particular bankstatementparser 0.0.20 ships
an explicit Apache-2.0 OR MIT choice despite its PyPI description emphasizing
Apache licensing. See [third-party notices](../THIRD_PARTY_NOTICES.md).

## Finding fixed: optional lxml floor

The prior OFX requirement inherited unbounded lxml from ofxparse, and the CAMT
backend allowed lxml >=5.0. Existing older installs could satisfy those ranges.
Optional extras now require lxml >=6.1.3,<7, retaining the tested backend version
and excluding releases before the reviewed entity-handling fixes. This adds no
new distribution to any runtime profile. Base dependencies remain unchanged.
Upstream [6.1.0 release notes](https://github.com/lxml/lxml/releases/tag/lxml-6.1.0)
cover iterparse/ETCompatXMLParser XXE defaults; [6.1.3](https://github.com/lxml/lxml/releases/tag/lxml-6.1.3-1)
fixes external parameter entity processing under internal-entity defaults.
These general upstream fixes are the basis for the floor; no exploit through
BankParser was demonstrated in this audit.

## Native-library scope

The inspected lxml wheel reports libxml2 2.14.6 and libxslt 1.1.43. Its pinned
[build workflow](https://github.com/lxml/lxml/blob/lxml-6.1.3-1/.github/workflows/wheels.yml)
and [build script](https://github.com/lxml/lxml/blob/lxml-6.1.3-1/buildlibxml.py)
include a libxslt backport. A raw native version comparison does not establish
whether an upstream fix is absent, and Python-package scanners do not establish
complete native coverage.

Reviewed native advisory candidates:

- [CVE-2026-0989](https://access.redhat.com/security/cve/CVE-2026-0989)
  concerns attacker-controlled RelaxNG schema inclusion recursion.
- [CVE-2026-6732](https://access.redhat.com/security/cve/CVE-2026-6732)
  concerns XSD validation with internal entity references.

Inference from the current BankParser/CAMT backend code: the supported parsing
entry points do not invoke RelaxNG, XSD validation or XSLT processing, so these
specific preconditions are outside the current API. This is a scoped call-path
review, not a claim that the underlying wheel is patched against every CVE.
Reassess before adding schema validation or exposing those native APIs. No scanner
ignore/allowlist was created from this analysis.

The inspected NumPy arm64 wheel uses system Accelerate, not bundled OpenBLAS/GCC
runtime libraries. Native binary/licenses vary by OS and wheel. Other-platform
verification remains a release task. Review native licenses before shipping a
container/application bundle; our wheel does not redistribute those dependencies.

## Reproduce and refresh

Release distribution jobs audit the exact runtime used for their clean-install
checks, separately for base, csv, ofx, camt, alternative and all on each tested
platform/artifact. Both advisory services must succeed before the manual workflow
can expose `validated-distributions`. Their `runtime-audit-*` artifacts retain
the inventory and JSON reports; scanner or inventory failures block the release.
Audit tools are installed outside the inspected runtime. The separate weekly
workflow remains a monitoring check.

Create separate runtime and audit-tool environments. Install BankParser/all in
runtime; install pip-audit==2.10.1 in tools. From the checkout, using the tools
Python (packaging is provided by pip-audit):

```sh
python scripts/inventory_dependencies.py --python /runtime/bin/python --output /tmp/runtime-audit
python -m pip_audit -r /tmp/runtime-audit/all.txt --no-deps --disable-pip --strict \
  --vulnerability-service pypi --format json --desc off --aliases on \
  --progress-spinner off --output /tmp/runtime-audit/pypi.json
python -m pip_audit -r /tmp/runtime-audit/all.txt --no-deps --disable-pip --strict \
  --vulnerability-service osv --format json --desc off --aliases on \
  --progress-spinner off --output /tmp/runtime-audit/osv.json
```

For a runtime installed with just one profile, add `--profile ofx` (or base, csv,
camt, alternative or all) to the inventory command and audit that profile's
`.txt` file. The default command above inventories every profile from an all-extra
installation. It does not install missing packages or audit unrelated tooling.

The complete closure is pinned before disabling resolution. Inventory validation
and report completeness must pass; network errors are failed audits, never
zero findings. Full package-artifact hashes are evidence from the pip installation
report; these pinned inputs intentionally do not claim hash-enforced installation.
The vulnerability workflow refreshes runtime checks on changes and weekly; manual
license/native review is still required when package versions or wheels change.
Known-advisory absence does not identify unknown vulnerabilities or malicious
packages. Build/dev tools, Python itself and the OS are outside this audit.
