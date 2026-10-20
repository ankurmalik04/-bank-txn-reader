# Contributing

Install from a checkout with Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,all]"
python corpus/generate.py --check
ruff check src tests corpus/generate.py scripts
mypy src/bankparser
python -m pytest --cov=bankparser --cov-branch --cov-report=term-missing
```

The base installation supports MT940 through WoLpH and native CSV. All native CSV
tests run without pandas or `bankstatementparser`. Optional conformance tests
skip when `bankstatementparser` is absent; use `all` to run the complete matrix.
CI also tests a base-only installation so optional adapters remain optional.

## Reporting a parsing problem

Include the BankParser version, parser implementation/version, file format,
exception code and location (or failed validation check), and the expected
canonical values. Supply a minimal synthetic reproducer. Remove real names,
account numbers, payment references and other confidential information before
opening a public issue. Preserve the formatting that triggers the problem.

For vulnerabilities or sensitive security concerns, follow
[SECURITY.md](SECURITY.md) and use GitHub private vulnerability reporting on this
repository. Keep vulnerability details out of public issues and pull
requests while the report is being assessed.

## Adding a regression

The [fixture provenance inventory](corpus/PROVENANCE.md) records the independently
authored corpus. For new fixtures, record the author/source, whether the input
was independently invented or derived, and any permission needed for
redistribution. Keep this record with the fixture and its independently authored
expectation. Changing identifiers in a customer export does not by itself
establish permission to publish that export.

Keep real exports and local credentials outside the repository. Environment
files are ignored as a convenience; ignore rules do not protect already tracked
files or replace review and secret scanning.

1. Add an invented scenario to `corpus/generate.py` under the relevant format.
   Run the generator to update its inputs, expectations and provenance hashes.
   Permitted external samples need a separate documented provenance/coverage
   policy before they become publication content.
2. Author the expected values independently from the source specification and
   fixture. Do not generate a golden file by dumping the parser under test.
3. Include every canonical transaction field, balance currencies, validation
   check outcomes and warning codes. Test source-specific `raw` fields separately.
4. Add the case to `corpus/regressions.json` with its supported implementations.
   Error fixtures specify an expected exception code.
5. Update `docs/compatibility.md` to state what the fixture establishes, and run
   the relevant conformance suite followed by the complete suite.

Agreement between two implementations does not establish correctness. Expected
account attribution, dates, references and amounts need independent evidence.
New formats or bank conventions should have an explicit support boundary and
actionable errors for unsupported cases.

## Building distributions

```bash
python -m build
```

The source archive includes tests, fixtures, examples and user documentation.
The wheel includes the Python package, type marker and MIT license. Check
changes to public fields and CLI exit codes against `CHANGELOG.md` before
releasing. Run `python scripts/check_distribution.py dist` to inspect built
archives. Keep generated build artifacts and local financial data out of commits.
