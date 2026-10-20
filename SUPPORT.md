# Support and compatibility policy

BankParser is an alpha library maintained on a best-effort basis. The current
0.5.0 development version is unreleased. Only the latest published alpha patch
will receive fixes once releases begin; older versions and arbitrary development
commits have no separate maintenance branch. There is no response-time or
resolution-time guarantee.

## Runtime support

Python 3.10–3.14 is the current declared target. CI exercises Linux on each of
those Python versions and macOS/Windows on Python 3.14. Distribution checks
cover base, csv, ofx, camt, alternative and all installation profiles.

Supported formats and their boundaries are in the
[compatibility guide](docs/compatibility.md). Coverage currently uses independently
authored synthetic inputs. A balanced statement does not prove authenticity,
complete extraction, bank compatibility or agreement with an accounting ledger.

## Public Python and JSON contracts

The documented Python API and CLI are the supported interfaces. Internal modules
and parser-specific raw metadata may change between alpha releases. Consumers
should read the changelog before upgrading and keep their own regression inputs.

The serialized canonical schema is 1.1; its version is separate from the package
version. Additive optional fields can increment the schema minor version. A
removed/renamed field, incompatible type or incompatible field meaning requires
a schema major version and migration notes. Consumers should tolerate additional
JSON keys and reject unsupported schema major versions explicitly.

Alpha package minor releases may change the documented API with migration notes.
Patch releases aim to preserve it, but correctness/security fixes can tighten
accepted input profiles, change erroneous values or reject previously accepted
files. Document such changes, warnings and error codes in CHANGELOG.md. Message
wording and raw metadata keys are not
stable compatibility guarantees.

## Asking for help

For ordinary bugs or feature requests, use the repository's Issues page. Include
package/Python/backend versions, the format, error code/location, expected
values and a minimal independently invented reproducer. Follow
[CONTRIBUTING.md](CONTRIBUTING.md).

Do not upload real bank statements, account identifiers, payment references,
credentials or other confidential data to public issues. For security concerns,
follow [SECURITY.md](SECURITY.md). Use GitHub's private vulnerability reporting
feature when it is enabled for this repository. If it is unavailable, ask for a
private contact without including vulnerability details or sensitive data.

For deployment on untrusted inputs, retain the input-size limit, avoid logging
raw contents and run parsing under application-level CPU/memory limits. Some
optional adapters use temporary files. Applications own retention, access control,
duplicate-import handling and downstream financial review.
