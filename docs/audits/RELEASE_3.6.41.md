# WayriCAD 3.6.41 publication

Published from `369994c81c1682a100420d9590e400d70b2fa4ed` after all eight
[CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40720263679) passed:
the configured Windows, Linux and macOS matrix and PI known-answer benchmarks.
The two superseded runs exposed a pytest nested-coordinate compatibility issue
and dependency expectations predating lightweight inspection. Coordinate
tolerances were preserved; worker tests now explicitly check inspection without
solver provisioning and 3D meshing without unused VTK dependencies.

## Packages and publication

The release has 24 independently installable PCM ZIPs, resources, Python wheel
and source archive, feed metadata, notes and SHA256SUMS.txt: 31 assets, about
74.33 MiB. All uploaded assets were downloaded and matched against local SHA-256
hashes before publication. Public PI, SI, thermal and feed URLs were checked
again afterward. The promoted PCM feed contains the exact released metadata.
Existing release assets, tags and commit history were preserved.

Official package schemas, payload syntax, icons, entrypoints and hashes passed.
The isolated wheel CLI/report smoke passed. Native KiCad Python CLI checks from
individually extracted PI/SI/thermal ZIPs passed without sibling source imports.
Their source members matched the tested checkout. The wheel matched 1,218 tracked
source members; the source archive matched 1,584. New control references,
screenshots, study inputs, common board tutorial and Blender modules were present.
Private staging, local boards, caches and environments were excluded.

## Local validation and limits

Windows native KiCad 10.0.6 / Python 3.11.5 checks included:

- Quick SI: 202 passed, one optional numerical-runtime skip.
- QuickTherm: 298 passed, two CalculiX-executable-dependent skips.
- Focused PI 3D, volume view and electrothermal checks: 32 passed.
- Updated PI dependency checks: seven passed.
- Isolated native live-current UI: seven passed; differential-probe UI: one passed.
- Native subprocess/shared-return checks: 39 passed.

The portable root run passed 691 tests, with 124 skips, after running the native
subprocess cases separately. Constraint Studio passed 382 local tests. These
counts describe separate scopes, not a count of unique tests across all runs.

A large combined native PI pytest process hit Windows wx heap error
`0xc0000374`; it is not a passing full-native-suite result. The affected live UI
file and differential probing passed in fresh native processes. A local portable
PI run passed 505 tests and skipped 83, but one GUI fixture failed because wx was
available without pcbnew; the same differential test passed in the required
native runtime. CI does not establish every native GUI interaction or a connected
editor workflow on every supported platform. These test-process limits remain
distinct from the successful isolated workflows and numerical checks.

PI coupled thermal extraction still rejects plated slots and nonplated holes.
The Marble Joule input reproduces that diagnostic; it is not a solved temperature
study. The explicit steady Joule example converged and exported reports.
White Rabbit's imported physical stackup remains unknown. No guard was removed,
board modified or unsupported physical input silently invented.

See the [PI](QUICK_PI_3D_SPEED_2026-10-28.md),
[SI](QUICK_SI_SPEED_GUIDE_2026-10-28.md),
[thermal](QUICKTHERM_SPEED_GUIDE_2026-10-28.md) and
[Blender](BLENDER_VISUALIZATION_2026-10-28.md) evidence for model assumptions,
timings, exact-result comparisons and genuine image provenance.

Original public board hashes were preserved. No private production board or
local installed plugin was changed. Temporary extracted ZIP copies created for
isolation checks were removed; current release assets and bounded verification
evidence were retained.
