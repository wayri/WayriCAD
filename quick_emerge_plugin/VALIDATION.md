# Quick EMerge development validation

Recorded 2026-10-28 on Windows. This is beta development evidence, not a hardware or
numerical qualification report. No production PCB was modified.

## Runtime and source

- Desktop: Python 3.14, wxPython 4.2.5, Matplotlib; native frame created and
  exercised outside the editor. KiCad CLI 10.0.6 is installed; no live IPC
  toolbar launch was exercised.
- Solver: Python 3.11.9, EMerge **3.0.0b9**, emsutil 1.1.4, NumPy 2.2.6,
  SciPy 1.17.1, Gmsh 4.15.2 and PyVista 0.49.0. An isolated validation
  environment reused existing scientific dependencies without modifying the
  shared environment. It is local test staging, not a portable deliverable.
- Adapter source target: upstream commit
  `446232037d175a596606c6c9ea986e372560566f`. Later releases require compatibility qualification before activation. The old 2.x layer/port/far-field contracts are not
  used as compatibility assumptions.

## Checks performed

- `python -m pytest quick_emerge_plugin/tests -q`:
  **80 passed, 5 skipped, 88 subtests passed**, including input geometry, non-finite rejection, reflection
  identities, EMerge 3 argument contracts, theta/phi ordering, Touchstone port
  order, stale inputs, isolated subprocess arguments, cancellation, result
  mismatch and a real missing-runtime subprocess.
- KiCad 10 Python `unittest` for `test_pcb_regions.py`: **5 native tests passed**.
  These five skip under the desktop interpreter because it has no `pcbnew`.
- `python -m unittest discover -s tests -v`: **382 tests, 70 skipped, no failures**.
  TEMP/TMP were directed to the repository scratch directory because the host
  sandbox denied the default temporary directory. Skips are not passes.
- KiCad 10 Python `compileall` checked the initial package; the final source
  was also compiled with the desktop Python after migration.
- Native GUI smoke: both model previews, edit invalidation, disabled Run until
  review, resize, solver worker launch, timer-based collection, all six native
  plot tabs, nearest field probe and sampled frequency metrics. Region studies
  add a seventh enclosure tab, source/geometry custody checks and read-only
  native-worker extraction.
- Local README/help references and the screenshot were checked. No suite
  release rebuild, install or feed promotion was performed as part of this recorded development evidence.

## Real EMerge 3 solves

All used SuperLU. These intentionally coarse models establish API execution,
result shape and visualization, not accuracy or acceptance:

| Study | Setup | Computed outputs |
| --- | --- | --- |
| Line coupon | 20 × 10 mm substrate, 1 mm thick, er 3.38; 10 × 2 mm top trace; PEC ground; 5 mm air margin; resolution 0.5; 2 mm edge mesh; 50 Ω ports; 1–2 GHz, 3 frequencies | Full 2-port S-matrix, 9 × 9 near-field plane at Z=2 mm, Touchstone |
| Patch | 40 × 40 mm substrate, 1 mm thick, er 3.38; 20 × 20 mm patch, 2 mm feed, two 3 × 5 mm inset slots; 10 mm air margin; resolution 0.4; 3 mm edge mesh; 50 Ω port; 4–5 GHz, 3 frequencies | S11, 9 × 9 near-field plane at Z=2 mm, 31 × 61 relative radiation surface at 4.5 GHz, Touchstone |
| Adaptive line | Same coupon; one mesh pass, five-sample AAA budget, tolerance 0.02 | Solver completed; mesh refinement reported **not converged**, and AAA reported reaching its sample limit. Neither is marked converged by the plugin. |
| Native end to end | Coupon launched through the actual wx controls using the isolated 3.x interpreter | Worker completed, full S-matrix collected, field and frequency probe labels exercised |

`help-workflow.png` and `help-viewport.png` are actual native-window captures of
the solved coarse patch field plane with linked markers and a line-cut overlay.
The title identifies its template scope. Local solver/output paths were
replaced with generic paths before capture; the source basename is a synthetic
context board. No numerical data were redacted or changed. The radiation radius
is normalized electric-field magnitude, not gain or physical distance.

## Viewport acceptance

Quick PI and QuickTherm's native visibility, color scale, camera and inspection
controls were inspected as the interaction benchmark. Added tests cover
nonuniform grid probing, unknown values, extrema, profile distances, scalar/log
limits, masked-cell omission, bounded large-grid display, radiation color
mapping, projection/picking and camera persistence. Native wx tests exercised
drag-vs-click discrimination, manual camera rotation followed by zoom, fit,
linked selection, pins and source-data preservation.
Actual Matplotlib mouse events dispatched through the native canvas exercised
each explicit Orbit, Pan, Zoom and Probe mode: angle changes during orbit,
translation with unchanged spans during pan, span changes during zoom, 3D
projected sample selection and 2D probing. Navigation gestures did not trigger
selection. Camera roll is retained across redraws.

The complete native-window workflow used the real coarse patch results:
selection in both field views, min/max navigation, two pinned samples, a
200-sample line profile, probe/profile CSV exports with hashes, manual and log
scales, dark/light views, panel resize and focus/restore. Setup edits cleared
results, pins, profiles and stale renderers. A native first-open managed runtime
also completed a real solver run through the updated window. These checks do
not establish GPU rendering or a measured frame-rate claim. The current
viewport displays the exported field plane, not an arbitrary 3D volume.

## Saved PCB rule-area studies

KiCad 10.0.6 native tests exercised a saved two-layer coupon with filled B.Cu
ground and a F.Cu signal crossing a named rule area. The actual board was
40 × 20 mm, while the selected area was X=10–30 mm and Y=5–15 mm. Saved dielectric
separation was 1.53 mm. Native tests verified exact clipping, concavity, a rule
hole splitting the trace, a rule area crossing the board edge, exclusion of an
outside via, rejection of an inside via, and source immutability. The isolated
worker was tested under `-I`, including source-overwrite rejection. A separate
board-only source directory and an existing project-directory manifest remained
byte-identical after worker shutdown; no project sidecars were created/changed.

Planner tests verify whole-span reference coverage (including holes), actual
rule-area cut interfaces, exclusion of natural board edges/existing board holes
from port candidates, other cut-net rejection, corner ambiguity, and no invented
interior feed. Review/run/collect tests reject source, region and port changes.

The saved coupon completed through both the scripted service and the native UI:
load enclosure list, choose SIGNAL/GND, review εr=4.2, preview two boundary ports,
solve 1–2 GHz at three frequencies with SuperLU, then collect all four S-parameters
and a 9 × 9 field plane retaining X=10–30/Y=5–15 mm. Board hashes remained equal.
This is API/geometry-custody smoke evidence, not numerical convergence acceptance.
`help-region.png` captures this native UI result; only local interpreter/output
paths were replaced with generic values. Its copper, coordinates and port labels
were preserved.

The runtime qualifier now also performs a synthetic polygon-region solve. A
stale certificate triggers requalification of the existing environment without
package installation; this was exercised with less than 3 GiB free and retained
the same active runtime/packages. Worker stdin is detached for reliable hidden
execution, including pytest capture on Windows.

Remaining region limits: two copper layers, lossless homogeneous dielectric,
PEC surfaces, bare copper and ideal boundary feeds. Inside drilled features,
multilayer/via-barrel/component models, interior feeds and curved rule-area
contours are unsupported; blocking diagnostics prevent silently incomplete
solves. Polygon validation is bounded before expensive planning. General
arbitrary-board extraction remains unqualified.

## Remaining numerical acceptance

Analytical line propagation/impedance references, patch resonance refinement,
air-boundary sensitivity, power balance, loss models and convergence acceptance
remain outstanding. The local PARDISO path failed while discovering MKL; this
was not repaired by changing shared dependencies. SuperLU is the explicit
working default. Optional accelerators remain untested. General populated/multilayer
KiCad extraction, via barrels, interior port mapping and the remaining upstream
capabilities are tracked in [CAPABILITIES.md](CAPABILITIES.md).

## Automatic dependency setup and updates

A real clean installation into a workspace-owned managed runtime completed:
EMerge 3.0.0b9 and all dependencies were downloaded from PyPI as binary wheels,
`pip check` passed, and the three real qualification solves passed before the
active manifest was published. The independent runtime resolved newer packages,
including NumPy 2.4.6 and PyVista 0.49.1, rather than inheriting the earlier
validation environment. A second `ensure` reused the active runtime. The actual
native first-open path selected it automatically, launched a real line solve,
and collected its full S-matrix successfully.

Manager tests cover release selection (including prereleases, excluding yanked
and development releases), isolated installation commands, dependency/solve
checks before activation, failed-update preservation, fallback to the tested
baseline, stale certificates, actual installed-version mismatch, low space,
concurrent setup locking, cancellation, rollback and path containment. Runner
tests cover stopping/reaping the worker even when Windows tree termination
fails or times out. Failed candidate installation and simulated future releases
use injected failures; there is no claim of testing a future upstream release.
Native UI checks also covered automatic setup callbacks, run gating,
cancellation and retry controls. Windows is the tested platform; POSIX
process-group cancellation is implemented but has not been run on a POSIX host.

The managed runtime occupies approximately **1.44 GB**, with about 18 MB of
earlier solver staging and small run artifacts. No source checkout, full build
tree or release ZIP was created. The validated runtime and logs are retained;
no pre-existing data or shared runtimes were removed. C: had approximately
2.2 GiB free after installation; this is not a measured net-free-space claim.
Future candidate installs require 3 GiB free and will defer safely while space
is below that threshold.


## Release candidate 3.6.43-beta.1

The prototype was promoted to an independent PCM package in a clean checkout
of upstream `36192f8195ee757c7dafdc44de7406179a435704`.
On Windows with Python 3.14, separate test processes recorded **726 passed,
124 skipped, 502 subtests passed** for the root suite and **86 passed,
5 skipped, 88 subtests passed** for Quick EMerge. These counts include native
wx/Matplotlib interaction tests on this host. The five native PCB extraction
tests also passed separately under KiCad 10.0.6 Python.

The extracted PCM installer passed all four real EMerge 3.0.0b9 qualification
solves in an existing isolated Python 3.11.9 runtime. Its native window passed
camera, linked probe, pinned sample, extrema, profile, CSV, theme, invalidation
and resize checks with measured coarse patch samples retained from development.
The refreshed workflow and focused viewport captures show this beta window;
path fields were set to generic example paths before capture. Samples are
unchanged, and these images do not demonstrate a converged antenna design.

All 25 installers passed official schema, payload, icon, entrypoint and hash
validation. Package documentation links and images passed validation. CI is
required on the release commit before publication; its run is linked from the
release notes. Live KiCad IPC toolbar launch remains unqualified. Scientific
convergence and unsupported upstream capabilities remain outside this beta.
