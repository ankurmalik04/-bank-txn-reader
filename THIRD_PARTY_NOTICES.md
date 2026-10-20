# Third-party dependency notices

BankParser's first-party code is MIT licensed. Dependencies retain their own
licenses. The BankParser wheel is a Python-only package and declares dependencies
for installation; it does not embed dependency wheels, native libraries or copied
upstream source. This inventory is an aid to review, not a replacement for each
distribution's complete license and notices.

Reviewed 9 October 2026. Exact runtime profiles, metadata and license-file SHA-256
values are in the [audit inventory](docs/audits/2026-10-09-dependencies/inventory.json).
The [audit report](docs/dependency-audit.md) records versions and scope.

| Distribution | Reviewed top-level license | Used by |
| --- | --- | --- |
| [mt-940](https://pypi.org/project/mt-940/5.1.1/) | BSD-3-Clause | Base |
| [ofxparse](https://pypi.org/project/ofxparse/0.21/) | MIT | OFX |
| [defusedxml](https://pypi.org/project/defusedxml/0.7.1/) | PSF-2.0; metadata uses PSFL | OFX, CAMT/alternative |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/4.15.0/) | MIT | OFX |
| [lxml](https://pypi.org/project/lxml/6.1.3/) | BSD-3-Clause plus component licenses | OFX, CAMT/alternative |
| [six](https://pypi.org/project/six/1.17.0/) | MIT | OFX, CAMT/alternative |
| [soupsieve](https://pypi.org/project/soupsieve/2.10/) | MIT | OFX |
| [typing-extensions](https://pypi.org/project/typing-extensions/4.16.0/) | PSF-2.0 | OFX, CAMT/alternative |
| [bankstatementparser](https://pypi.org/project/bankstatementparser/0.0.20/) | Apache-2.0 OR MIT; shipped files expressly offer either | CAMT/alternative |
| [pandas](https://pypi.org/project/pandas/2.3.3/) | BSD-3-Clause plus incorporated-code notices | CAMT/alternative |
| [numpy](https://pypi.org/project/numpy/2.5.3/) | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0, plus platform-native notices | CAMT/alternative |
| [python-dateutil](https://pypi.org/project/python-dateutil/2.9.0.post0/) | BSD-3-Clause; some contributions also Apache-2.0 | CAMT/alternative |
| [pytz](https://pypi.org/project/pytz/2026.5/) | MIT | CAMT/alternative |
| [tzdata](https://pypi.org/project/tzdata/2026.5/) | Apache-2.0 plus IANA timezone-data notices | CAMT/alternative |
| [pydantic](https://pypi.org/project/pydantic/2.14.0/) | MIT | CAMT/alternative |
| [pydantic-core](https://pypi.org/project/pydantic-core/2.50.0/) | MIT | CAMT/alternative |
| [annotated-types](https://pypi.org/project/annotated-types/0.8.0/) | MIT | CAMT/alternative |
| [typing-inspection](https://pypi.org/project/typing-inspection/0.4.4/) | MIT | CAMT/alternative |

Pydantic 2.13.5/core 2.46.5 in the previously tested environment were also
reviewed; fresh resolution chose 2.14.0/core 2.50.0. Both pairs ship MIT notices.
BankParser does not select a license on behalf of downstream redistributors.

## Native and embedded components

The reviewed lxml LICENSES.txt documents PSF/ElementTree components, separate
schematron-resource terms, a GPL source test runner, and binary dependencies:
libxml2/libxslt/libexslt (MIT), zlib (Zlib), and iconv (LGPL-2.1).
Some schematron resources are described there as unlicensed. Their presence and
terms need explicit review if redistributing lxml itself; this is not an
all-components BSD clearance. BankParser does not expose XSLT/Schematron APIs.
See [upstream licensing](https://lxml.de/licenses.html) and the exact wheel's notices.

NumPy's wheel notice includes OpenBLAS/LAPACK BSD terms, GCC runtime
GPL-3.0-or-later WITH GCC-exception-3.1, and libquadmath LGPL-2.1-or-later,
while warning that listed components do not necessarily occur in every binary.
The inspected macOS arm64 wheel uses system Accelerate and contains no .dylibs
or numpy.libs bundle. Other platforms can differ. The GNU exception and LGPL
terms must not be reduced to plain MIT/BSD labels.

If distributing dependency wheels, an installed application, container or binary
bundle, retain upstream copyright/license/NOTICE files and assess that bundle's
source, modification and relinking obligations, including native libraries.
Do not strip notices, treat this table as the complete licenses, or infer that
our Python-only wheel audit clears a different bundled distribution. Development,
build and audit tools are outside this runtime inventory.
