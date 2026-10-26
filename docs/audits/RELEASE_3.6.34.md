# WayriCAD 3.6.34 release evidence

This incremental release packages the AC/SMPS copper workflow added after
3.6.33. It preserves the existing published 3.6.33 binaries and tags.

## Functional evidence

See [AC validation](QUICK_PI_AC_2026-10-27.md) for the numerical model, independent
analytical references, fixed-temperature Joule interpretation and unsupported
geometry. The final native run passed 39 tests on Windows with KiCad 10.0.6,
Python 3.11.5 and wxPython 4.2.2. It covers AC physics, worker/report/UI behaviour
and native VTK mesh acceptance. Three report visuals and their selection/probe
interactions passed in Edge with no JavaScript errors.

The actual managed-runtime CLI and an independently extracted PI installer ran
the synthetic example and exported paired HTML/JSON. Production module bytes
were checked against the installer. This is synthetic/reference validation,
not validation against a measured switching converter.

This release preparation changes package versions, download documentation and
metadata, without changing the tested AC numerical equations or UI behaviour.
All active packages receive a new version so PCM can update their shared runtime
catalogue as well. Candidate feed metadata stays unpublished until all referenced
assets are uploaded and verified.

## Publication

Published [3.6.34](https://github.com/wayri/WayriCAD/releases/tag/v3.6.34)
from `ceda5afd2b0ac848cbbac54097d613f265a6e970`. All eight
[exact-source CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40398264525)
passed, covering Linux, Windows and macOS portable checks and PI references.

All 24 final PCM archives pass schema, syntax, icon, runtime/action and hash
validation. The final isolated PI installer ran the AC example and exported its
report. The clean wheel passed isolated CLI/report/mechanical smoke checks;
its AC production modules match source and contain no tests or bytecode.
The source archive's 1,322 tracked members match checkout bytes. Nine root
version/CLI checks with 24 subtests and 32 Analytics packaging checks passed.

All 31 uploaded assets were downloaded and matched the local SHA-256 manifest
before publication. Public PI/SI installer and feed downloads were checked again
after publication. The PCM feed is promoted from those verified release bytes.
Earlier release assets were preserved. No local plugin installation was made.
