# Quick-tool workspace polish — 4.0.1

## User-visible changes

Quick PI explains missing source/load selections, overlapping grouped contacts,
stale saved-board data and unsupported model combinations before Run. The toolbar
and Setup action share readiness and its tooltip. Guidance stays inside the
scrollable Setup pane; no additional viewport header is introduced.

Loss/probe tables copy a selected row with Ctrl+C, or the complete current table
with Ctrl+Shift+C. The context menu exposes both actions. Exported tab-separated
text retains the stored numeric precision rather than the shortened display
format; embedded line breaks and tabs cannot split a record. Sorting and native
selection identities remain in place, and leaving a row clears its hover text.

Quick SI derives its header from the completed report actually displayed,
including selected multi-net cases, rather than unrelated drafted main inputs.
It identifies route delay and Board RLC, ideal-line or unavailable eye results.
The full reason remains in the tooltip and Details. An unavailable requested
eye retains Route instead of forcing an empty plot. Input changes clear stale
model labels and numerical feedback with the previous result.

Quick EMerge keeps 2D/3D navigation and a solved-results toggle above the
viewport, without geometry axes, graph borders, grids or inset plot margins.
Geometry fit targets the active antenna/signal copper and feed ports; full-region
fit remains available without changing the simulation domain. Charts, summary
tables, probe details and specialist controls remain
available through More. Parametric templates now have a populated 2D plan using
the same geometry descriptors as the existing 3D preview. This changes preview
presentation, not FEM equations or the scope of imported PCB copper.

The Export menu groups 2D PNG plots, current-camera 3D PNG views and existing
HTML/PDF reports. Choosers start in the board's project directory. Plot exports
check source/setup custody before and after rendering and replace a destination
only after a valid PNG is ready. Unavailable solved fields are not replaced with
geometry under a result label. A 3D PNG is a still image; the native viewer
retains its interactive camera.

Radiation views add XZ/YZ/azimuth polar cuts alongside the interactive 3D
relative-field surface. Both normalize against the same maximum known stored
sample. Cuts retain actual angular indices and gaps; duplicated azimuth seams
cannot invent a missing half-plane. Isotropic, dipole and asymmetric analytical
patterns independently check plane selection and normalization. Actual antenna
cut probes also match their recorded values and 3D radii within 1e-12. Reports
resolve angular pins from the source samples rather than trusting display text.
These are relative-field patterns, not gain in dBi or efficiency.

Reports show an active-study settings table with readable labels and units.
Region dimensions and dielectric separation come from the recorded geometry.
Full canonical settings remain in collapsed HTML/JSON evidence; PDF replaces
that block with a provenance note instead of printing dictionary text and
inactive defaults. This presentation change passed 24 focused checks and 12
subtests, plus readback of the actual antenna result's material/solver settings.

These changes do not alter the PI solver or SI channel equations. The previously
unreleased [board-derived RLC eye](../../signal_integrity_advisor_plugin/BOARD_RLC_EYE.md)
is included in the 4.0.1 packages, with its separate analytical and native
[validation record](BOARD_RLC_EYE_2026-10-30.md). Its DC-R / quasi-static-LC scope
does not include skin/dielectric loss, nonlinear IBIS or LPDDR4 training/ODT.

## Checks and scope

Focused native tests cover synchronized Run states, overlap/staleness recovery,
clipboard dispatch with a mocked clipboard, unchanged row selection, model-aware
eye navigation, numerical rows and displayed-case identity. The user's real
clipboard and PCB projects are not used. Viewport, setup persistence and result
probe tests retain their existing assertions.

The initial EMerge native workspace run passed 34 tests without skips, including
2D/3D switching, preserved cameras, menu dispatch, viewport sizing, project-folder
choosers and atomic exports. Its renderer/report run passed 38 tests with one
optional PDF-readback skip. A hardware export regression caught and fixed an
initial blank VTK buffer: capture now requires an attached viewport at its actual
size, renders before reading the back buffer and checks image dimensions.

The radiation addition passed 27 analytical/report checks, eight focused native
checks and all 13 native scene checks. Picking coincident volume samples now
uses visible cell depth, then resolves an original stored sample; it does not
return an interpolated field value. Volume fit includes the stored Z layers.
Radiation retains a separate normalized camera instead of inheriting the PCB's
millimetre bounds. Polar probes, radial zoom, partial coverage, exports and
stale angular-pin rejection are covered.

The release procedure runs shared root tests, SI regressions, affected PI setup
and return tests, EMerge regressions, package/document validators and isolated
wheel smoke checks. CI includes the complete SI source suite in its existing
Windows/Linux/macOS matrix. Native tests use Windows, KiCad 10.0.6, Python 3.11
and wxPython 4.2.2 for PI/SI. EMerge additionally exercises its workspace and
exports with complete wxPython 4.3.2 / VTK 9.7.1 and the Matplotlib fallback with
Python 3.14 / wxPython 4.2.5. CI without KiCad is not proof of native compatibility on all
platforms; skipped checks remain skips. Exact counts and logs are recorded with
the release artifacts and the CI run linked from the release.

The independent ZIP/wheel checks cover bundled channel code, help and pictures;
no sibling install may supply missing backend modules. The fanout visual
catalogue now includes its nested PNG/JSON assets in the wheel as well as PCM.
Six unchanged standalone SWIG ZIPs retain their existing versions and are
compared byte-for-byte against the prior release.

The first candidate failed the saved-example provenance check: its numerical
producer hashes preceded the RLC eye change. Examples were regenerated through
the native services instead of substituting hashes. PI/thermal retain the
original exact-byte fixture and floating-island tests. SI now uses a separate
copy with only the intentional island removed; native geometry and stackup
comparison verifies the derivation. Source bindings, RLC convergence and actual
viewer-adapter readback are checked for the regenerated results.
All ten example checks passed with native and actual viewer opt-ins enabled,
including fresh-folder reproduction and rejection of changed trace geometry or
dielectric stackup. The generator uses native permanent deletion for its one
discarded fixture item, avoiding a detached Python-owned track outliving its
parent during later native reads. No plugin solver or UI source changed in this
example refresh.

## Screenshot provenance

The new opaque native captures are dated 2026-11-01. Existing larger screenshots
remain available in the READMEs with their original capture versions.

- [Quick EMerge](../../quick_emerge_plugin/help-minimal-workspace-4.0.1.png):
  1280 × 800 native window, 1264 × 738 client and 1264 × 639 canvas with panels
  closed. Windows, Python 3.11.5 / wxPython 4.3.2 / VTK 9.7.1; Matplotlib renders
  the 2D view.
  Actual clipped copper from the public `antenna_region` PCB fixture, including
  the patch, feed and one boundary port. Native KiCad 10.0.6 extraction has no
  planning blockers; no solved FEM field is represented. The larger source PCB
  is unchanged. No private paths or redactions. The fixture's three native DRC
  findings and lack of antenna qualification are documented beside the fixture.
- [Actual antenna field](../../quick_emerge_plugin/help-antenna-field-4.0.1.png):
  the same native workspace displays original 21 × 21 E samples at 2.4 GHz,
  Z=2 mm, with actual saved signal-copper contours. The one-port region completed
  a three-frequency 2.3–2.5 GHz solve under EMerge 3.0.0b9 / SuperLU, producing
  S11, near-field and radiation data. This is coarse end-to-end execution
  evidence, not mesh/boundary convergence or measured antenna qualification.
- [2D radiation](../../quick_emerge_plugin/help-antenna-radiation-2d-4.0.1.png)
  and [3D radiation](../../quick_emerge_plugin/help-antenna-radiation-3d-4.0.1.png):
  native 1264 × 738 clients with 1264 × 602 canvases, using the same 2.4 GHz
  result and its original 91 × 181 angular samples. Windows, Python 3.11.5,
  wxPython 4.3.2 and VTK 9.7.1. Both use the same stored-peak normalization;
  neither is gain or efficiency. No private paths or redactions.
- [Quick PI](../../quick_pi_plugin/help-workspace-polish-4.0.1.png): native
  1280 × 860 window on a synthetic demonstration PCB with optional panels open.
  The 0.711492 mV field comes from the analytical 65 × 90 mm copper-plate test;
  the illustrated footprints are layout context and are not that solved geometry.
  This is a UI/result presentation fixture, not a measured-board validation.
- [Quick SI](../../signal_integrity_advisor_plugin/help-result-feedback.png):
  native 1280 × 800 window, 1212 × 546 eye canvas, actual extracted 60 mm
  synthetic route over filled references. Explicit inputs are 1 Gb/s, 1 V
  open-circuit swing, 50 ohm source, open receiver with 2 pF C and 0.1 ns edge.
  This is the linear board RLC model, not an IBIS or compliance result.

Original fixture PCB bytes are checked unchanged. Captures contain no personal
paths, private designs or credentials; no redactions were needed. Local capture
scripts and geometry/model receipts are retained in the ignored
`.validation/release-4.0.1/` evidence folder. No user design is packaged.
