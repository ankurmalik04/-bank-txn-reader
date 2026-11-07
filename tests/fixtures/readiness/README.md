# Pre-refactor assessment compatibility fixtures

`pre_refactor_assessments.json` contains complete `to_primitive(assess_import(...))`
outputs captured from commit `512020378b1ccecb48366b628298b39b6a26b608`
(PR #16, before the readiness module separation in PR #17).

The deterministic synthetic inputs are defined by `compatibility_assessment()`
in `tests/test_import_readiness.py`. The cases cover pending and accepted
duplicate reviews, a permissive policy with missing fields, confirmed destination
mapping, a destination currency conflict, and recomputed validation failure
despite a permissive policy and a previously passed recorded validation.

The accepted duplicate token was also captured from this baseline, rather than
calculated by the implementation under test. The snapshots preserve the entire
serialized result, including ordered reasons and checks, policy and destination
fields, fingerprints, and reviewed flags. Tests read these committed expectations;
they never regenerate them.

To audit the capture, load `tests/test_import_readiness.py` with `runpy.run_path`
in a separate process whose `PYTHONPATH` points at the baseline commit's `src`
directory. For each fixture key, serialize
`to_primitive(compatibility_assessment(key))` using that baseline implementation
and compare it with the committed JSON. Verify `bankparser.readiness.__file__`
points into the baseline checkout before capturing outputs. Do not refresh these
fixtures from the current implementation merely to make a failing test pass;
any intentional contract change needs explicit review.
