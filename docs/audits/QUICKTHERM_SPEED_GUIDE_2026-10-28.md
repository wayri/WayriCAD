# QuickTherm geometry speed and complete guide verification

Date: 2026-10-28. Windows, KiCad 10.0.6 native Python 3.11.5, NumPy/SciPy,
wxPython 4.2.2. These are source changes; published installers were not replaced.

## Scope and bottleneck

A fresh-process Marble multilayer study used the existing saved four-source
illustrative inputs, manual 32-cell long-axis resolution, source refinement 1,
12 saved copper layers, and no mesh-acceptance sweep. No previous solved result,
mesh or conductivity matrix was reused. Sources were U1 5 W / 5 K/W RθJB,
U35 2 W / 8 K/W, U23 0.5 W / 10 K/W and U54 0.8 W / 10 K/W. Ambient was 25 °C;
dielectric k 0.3 W/(m·K), copper k 385 W/(m·K), plating 0.025 mm, emissivity 0.8
and explicit h 9 W/(m²·K). These assumptions do not establish board operating data.

The pre-change cProfile run took 253.224 s with 801 million Python calls.
Multilayer assembly consumed 236.4 s: face transport 98.5 s, polygon containment
95.5 s, and conservative cell-intersection fallback 78.2 s. Those nested times
overlap. Repeated scans of unrelated holes/edges dominated; sparse factorization
was not the main obstacle. Profiling overhead is substantial and these values
must not be presented as ordinary user solve times.

## Changes

- A bounded polygon-to-active-cell broad phase replaces all-polygons-for-every-
  cell scanning. Exact prior bounds, clipping and conductivity predicates still
  decide membership. Original polygon order is retained; broad index storage
  falls back to the original scan if it would exceed two million assignments.
- Hole bounds use a local spatial grid; large polygons use Y-edge scan bins.
  These only remove impossible candidates. Boundary predicates and tolerances,
  clipped areas, holes, unknowns and source-contact rules are unchanged.
- New indices live in a thread-local ContextVar for exactly one solve and are
  discarded in `finally` on success or failure. They are not attached to public
  geometry, serialized into reports or reused across later geometry revisions.
- Circular barrel distance/reach values and identical-radius annulus stencils
  are computed once per barrel/run rather than repeated on every layer pair.
  Pair-specific land verification, span checks and unresolved counters remain.
- With zero radiative coefficients, steady and transient systems are linear:
  one accepted linear solve replaces an identical second Newton solve. Transient
  factor-cache hits also reuse the fixed-node coupling block rather than rebuild
  sparse matrices before looking up the factor. Nonzero radiation retains Newton
  iteration and the existing convergence tests.
- Initial inspection extracts each named footprint's properties once instead of
  twice. Anonymous and asterisk graphic containers are excluded from thermal
  reference lists; named duplicate component references still raise an error.

## Timings and numerical equivalence

| Check | Before | Final optimized | Interpretation |
|---|---:|---:|---|
| Fresh-process Marble read/geometry/steady solve | 93.072 s | 65.020 s | Same board, input values and mesh; about 1.43× faster in this final pair |
| Zero-radiation spatial transient kernel, 2,000 nodes / 200 steps | 0.21145 s | 0.06967 s | About 3.03×; excludes board load/extraction and scientific-module startup |
| White Rabbit declared thin-sheet tutorial | Not a speed comparison | 2.055 s | Actual three-source run after fixing anonymous import containers |

An earlier optimized Marble iteration took 35.892 s; it preceded the stronger
cache-lifetime cleanup and ran amid different concurrent workload. It is retained
as development evidence, not used to claim a stable 2.6× final speedup. Processes
were fresh, but OS file caches were not flushed and other work was active.
These observations are not a cross-machine benchmark or a guarantee for every mesh.

The full before/final Marble result trees matched exactly: 131,815 numeric values,
maximum absolute difference **0**, and identical structural, identity, unknown,
coverage and warning values. The reference came from tracked pre-change source
`e4a3e684`; no archived source tree or old interpreter was copied.

Additional fixtures compare indexed/unindexed assembled sparse matrices and
right-hand sides exactly, including active cells, complete layer fields,
components and heat balance. Randomized point and rectangle queries, hole/edge
boundaries and a changed-geometry second solve test candidate completeness and
cache lifetime. The linear transient comparison retained 200 steps and identical
maximum energy residual 7.0171e-10 W; final-temperature difference was
1.0658e-14 °C. Existing spatial, multilayer and native-board tests passed.

## Runnable public-board tutorials and images

The expanded [user guide](../../quick_therm_plugin/QUICK_THERM_USER_GUIDE.md) and
[offline HTML edition](../../quick_therm_plugin/QUICK_THERM_USER_GUIDE.html) cover
the main window, source table, all environment and board-model fields, heat paths,
package-contact columns, RC storage, CalculiX, every playback/view control,
result/probe columns, reports, Blender, and main CLI options. All 48 explicit
labels from the native widget inventory are represented; dynamic numeric fields
and the physical-contact table have separate references. It includes complete
copyable configurations rather than only configuration fragments:

- [Marble steady](../../quick_therm_plugin/studies/marble-steady.json)
- [Marble spatial transient](../../quick_therm_plugin/studies/marble-transient.json)
- [White Rabbit thin sheet](../../quick_therm_plugin/studies/white-rabbit-thin-sheet.json)

Updated-source `--config` accepts an explicit manual input mode, reviewed values
and nonempty exact reference scope, matching the already implemented native
manual-input service. It therefore does not require adding artificial thermal
fields to the public PCBs. Saved-field mode retains its required power mapping.
Invalid mode, missing manual scope and missing values are rejected before workers.

The real White Rabbit native Altium import lacked a verified physical stackup,
so its tutorial deliberately uses an assumed thin sheet, not fabricated layered
materials. IC1/IC2/U1 dissipate 0.5/0.25/0.15 W with RθJB 10 K/W, ambient 25 °C,
effective k 20 W/(m·K), emissivity 0.8, zero airflow and manual 40-cell resolution.
It returned 40.1890 / 35.1799 / 32.0563 °C junction estimates. These are illustrative
model outputs, not a qualification of White Rabbit. Anonymous import containers
initially caused duplicate-empty-reference errors; the named-component fix was
tested, and named duplicates remain rejected.

Three new figures use the production thermal plotter: saved Marble steady fields,
actual White Rabbit thin-sheet output, and actual stored Marble transient states
at 0 / 0.5 / 1 s. The latter has a 24-cell manual grid, 0.1 s integration/storage,
U1 off at 0.5 s, initial 25 °C and declared copper/dielectric capacities
3.45e6 / 1.8e6 J/(m³·K). Its ten steps and eleven stored frames had maximum energy
residual 9.9254e-13 W. No intermediate temperature was invented for the figure.
The figures are analysis plots, not mock native-window screenshots.

All source boards were read-only and retained their hashes. See the shared
[public-board reference](../QUICK_TOOL_EXAMPLE_BOARDS.md) for revisions, original
versus imported bytes and limitations. The images were visually inspected and
their metadata checked for personal paths. The guide was regenerated from clean
UTF-8 after an intermediate script encoding error; both final editions contain
no mojibake or replacement characters. Links, images and 41 HTML anchors passed.

## Final release checks

The complete QuickTherm pytest suite ran on KiCad's native Python 3.11.5:
**298 passed, 2 skipped**, with 223 passing unittest subtests, in 59.05 s.
The two skipped checks require an explicitly configured CalculiX executable
(`WAYRICAD_TEST_CCX`); no external CalculiX solve is claimed by this test run.
Existing pure-Python pytest dependencies were reused; no runtime was installed.
The native component workspace and asynchronous whole-board window workflows
passed, including the inspector note width, source edits, solve, views and reports.
An earlier sandbox run could not atomically publish report files in its temporary
directory; the same complete suite passed with normal filesystem permissions.
Those sandbox failures were not treated as numerical failures or hidden skips.

The public Marble and imported White Rabbit boards retained their recorded
SHA-256 hashes. No board was modified. The three new plot images contain only
software attribution and image-resolution metadata, with no personal paths.
The standalone PI electrothermal integration retains its separate geometry
restrictions; these QuickTherm checks do not establish that it supports the same
slot and nonplated-hole geometries as QuickTherm.
