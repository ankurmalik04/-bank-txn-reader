# Installation dependencies

The base package requires only `mt-940>=5.1.1,<6`. MT940 and native CSV parse
without pandas, NumPy or XML dependencies. Python 3.10 or newer is required.

All extras that install lxml now require `lxml>=6.1.3,<7`, the tested security
floor. See the [dated dependency audit](dependency-audit.md) and
[third-party notices](../THIRD_PARTY_NOTICES.md) for runtime license evidence,
advisory results and native-wheel limits.

| Extra | Direct optional dependencies | Purpose |
| --- | --- | --- |
| `ofx` | `ofxparse==0.21`, `defusedxml>=0.7.1,<0.8`, `lxml>=6.1.3,<7` | Default bank/card OFX and QFX adapter, bounded SGML and hardened XML source checks |
| `camt` | `bankstatementparser==0.0.20`, `lxml>=6.1.3,<7` | Current CAMT adapter; inherits the upstream pandas dependency |
| `alternative` | `bankstatementparser==0.0.20`, `lxml>=6.1.3,<7` | Explicit compatibility backend for supported families |
| `csv` | None | Compatibility installation name; native CSV is already included |
| `all` | Both optional backend sets | All currently registered adapters |

`ofxparse` brings Beautiful Soup, lxml and six transitively; Beautiful Soup has
its own dependencies. The OFX-only installation no longer needs pandas or NumPy.
This does not make the OFX extra dependency-free. Removing lxml requires an
upstream dependency change or a separately maintained and verified alternative.
BankParser imports optional backends only when selected.

The guarded OFX adapter retains source-local dates and exact Decimal amounts,
checks transaction identities/counts against the backend and rejects unsupported
corrections, pending activity, investment scopes and foreign-currency semantics.
The [compatibility guide](compatibility.md) defines the bounded support contract.

Native CAMT is deferred pending version-specific schema analysis, multi-detail
conservation, status/balance semantics and permitted bank/exporter samples.
Pandas conversion can be a separate optional output utility if users need it;
the canonical model and JSON serialization do not require DataFrames. See the
[serialized examples](../examples/output/).
