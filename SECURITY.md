# Security policy

## Supported versions

BankParser is an alpha library. Version 0.5.0a1 is the first alpha pre-release.
Security fixes will target the latest published alpha patch;
older releases and development commits have no separate maintenance branch.
See [SUPPORT.md](SUPPORT.md) for compatibility and support scope.

## Report a vulnerability privately

Use GitHub's **Report a vulnerability** option on this repository's **Security
and quality** tab. Private vulnerability reporting is enabled for the public repository. See
[GitHub's reporting instructions](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).
If that option is unavailable, open an ordinary issue asking maintainers for a
private contact. Do not include vulnerability details or sensitive attachments
in that issue.

Include enough information to reproduce and assess the problem:

- BankParser, Python and optional backend versions, operating system and format.
- A minimal independently invented input and reproduction code or command.
- Expected and actual behaviour, error codes/locations and potential impact.
- Any proposed mitigation or patch, if available.

Do not include real bank statements, account identifiers, payment references,
credentials or other confidential data, even in a private report. Use synthetic
data. Keep exploit details out of public issues, discussions and pull requests
while maintainers assess the report.

## Handling reports

Maintainers review reports on a best-effort basis, request clarification through
the private advisory and coordinate fixes and disclosure with the reporter.
There is no guaranteed response or resolution time and no bounty programme.
Confirmed fixes will be described in release notes and, where appropriate, a
security advisory. Ordinary parser bugs and unsupported formats belong in Issues;
use private reporting when security or sensitive disclosure is involved.

Input bounds and hardened XML handling do not replace application-level CPU,
memory, access-control and logging safeguards. See the
[dependency audit](docs/dependency-audit.md) for the scope of package and native
dependency checks.
