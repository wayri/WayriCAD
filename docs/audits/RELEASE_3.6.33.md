# WayriCAD 3.6.33 validation

Windows; KiCad 10.0.6, bundled Python 3.11.5, wxPython 4.2.2, NumPy 2.4.2,
SciPy 1.17.1 and Matplotlib 3.10.8. Portable checks also use Python 3.14.2.
Original user designs were not edited. Public Marble was read from an existing
copy, SHA-256 `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.

## Models

Quick PI solves fixed-temperature DC copper conduction. The new melt screen
integrates density × Cp(T) / resistivity(T) to obtain a J²t action threshold,
then adds latent heat at melting. Cp uses NIST-JANAF pure copper, 250–1358 K;
linear electrical resistivity and fixed density/current distribution are explicit
approximations. Cooling, substrate heat flow, expansion and arcing are absent.
Melting is distinct from opening/clearing. Out-of-range material inputs remain
unavailable. Local peaks depend on mesh/contact geometry. Bottlenecks are spatially
separated high-J regions, not a proof of the minimum geometric cut section.

Eight dedicated tests cover tabulated enthalpy, quadrature admission, inverse-I²
time, actual barrel-area² I²t, straight-track association, remote regions, live
rescaling and unsupported 3D. Thirty solver/analytics/report regressions passed.
Independent sink changes reuse the mesh but re-solve the electrical field;
proportional total changes retain the faster scaling model. Native current-control
checks passed, including both sink targets, unchanged other demands, acceleration,
ordinary zoom, superseded-result rejection and saved-source invalidation.

Quick SI colours exact same-layer straight-track edge gaps, with parallel overlap
reported separately. A bounded grid index avoids an all-pairs board scan. The
optional local NEXT model retains its ideal-plane/material/matched-port assumptions
and numerical convergence gates. Arcs, vias, pads, zones and broadside coupling
are omitted and counted; no zero-interference claim follows from an empty map.
Eleven new geometry/native/CLI and eleven existing crosstalk checks passed.
Marble MDC: 37,379 indexed tracks, 294 distinct comparisons, 103 neighbours,
complete search in 2.531 seconds (15.794 seconds including native startup, board
load and HTML/JSON export). No local voltage model was assumed. A sparse native
10,000-track fixture used 40,000 index visits in 0.453 seconds, versus 49,995,000
possible naive pairs; it found no neighbours within the chosen radius.

## Visual and source evidence

The SI native probe verifies actual worker results, paint, selection, filtering,
readouts and unchanged source. Its bare unittest run stalls during KiCad/wx
teardown; assertions and the separately captured owned probe are not claimed as
normal process-exit evidence. The independent HTML browser check passes actual
painted geometry selection, filtering, units, unknown values and zero JS errors.
The PI fusing screenshot shows actual synthetic solved copper, melt colours,
ranked-region markers and selection highlights. Its bounded standalone inspector
re-run passed in 6.416 seconds with normal process exit. The actual Quick SI
frame also opened and exited its normal MainLoop while cancelling an owned
neighbour worker; no forced process exit was used. Mixed native table test
shutdown remains distinct from these lifecycle checks. The native sink-wheel
suite exited normally.

Earlier Analytics, Mechanical and first-open copper evidence is linked from the
[suite audit](SUITE_WORKFLOW_RELIABILITY_2026-10-26.md) and
[copper workflow audit](ANALYTICS_COPPER_WORKFLOW_2026-10-26.md).

Exact-source CI and published asset verification must pass before feed promotion.

## Marble PI and current interaction

The real saved-board solve used 23,511 triangles, four ideal source pads and a
0.2 A load. It completed in 15.625 seconds: sink voltage 1.1884286745343724 V,
loss 0.002314265093131874 W, relative energy error 2.75e-12. These voltage/loss
values match the prior solve. Copper melting onset action is 92,633.4806
A²s/mm⁴ under the declared model. Updating the load to 0.3 A on the existing
mesh took 0.453 seconds, with relative energy error 6.66e-16. Source hash stayed
unchanged. This is one local benchmark, not a hardware-independent guarantee.

The cursor popup reads local values in constant time, shows before/after and
signed changes, and leaves pending/unsupported fields unknown. Projected-layer
local ambiguity is retained. Dedicated tests cover selected/all metrics and
quadratic loss/melting scaling. Native sink checks cover both sink targets,
revised proportional tuning, and popup teardown across repeated frames.

Losses now uses separate By layer and Heating subtabs with sortable tables.
Probe uses Parameter/Value/Unit rows, metric switching and map/object focus.
Numeric sorting keeps unknowns last and retains identities; manual column widths
persist. Old paragraph details remain collapsed. Four table assertions cover
sorting, cross-selection, source invalidation and narrow/wide layouts; normal
exit for the mixed native table test process is recorded separately.

Final integrated native PI run: 37 tests passed in 77.839 seconds, process exit 0,
including fusing, independent loads, cursor before/after/all-metrics, native wheel,
sortable tables, inspector cross-selection and stale-source checks. Earlier mixed
standalone teardown stalls were not counted as passes; this integrated run did
exit normally. Narrow probe columns subsequently retain at least 90 px for values
and 60 px for units, with native horizontal scrolling instead of crushed cells.

After the final column sizing correction, six native sink/table tests passed in
16.264 seconds with process exit 0. The release screenshots are direct native
captures of synthetic fixtures (PI cursor, Probe, layer-loss table and SI
neighbours); no private paths, design content or edited numerical values appear.

A final native SI capture used the ordinary application MainLoop and exited
normally (exit 0), including real worker calculation, paint, selection and
source custody; no os._exit was used. This supersedes the earlier forced-exit
capture as the release screenshot evidence.

## Final local portable and isolation checks

Complete portable PI suite: 369 passed, 64 skipped and 410 subtests passed.
Source-only documentation and packaged-image links pass. The isolated wheel
passes CLI/report-asset/mechanical-rule smoke checks. The source archive's
1,310 tracked members match the checkout bytes; private validation directories,
caches and user boards are excluded.

Independent PCM production imports were verified against archive bytes, with
external test helpers staged separately. PI: 15 core tests plus four native
sink/cursor/table/inspector tests, zero skips, normal process exit. SI: 11 new
geometry/native/CLI cases, zero skips. Aliases replace only action registration;
production modules and the owned analysis workers come from each extracted ZIP.
The auxiliary BOM package descriptor now matches 3.6.33; its 32 focused
packaging/version tests pass. Scientific reference URLs remain in offline report
provenance; tests reject active remote resources rather than deleting citations.

The final wheel excludes development tests and bytecode caches; source-archive
tests remain available. An explicit artifact check found zero test members, and
the cleaned wheel passed all CLI/report-asset/mechanical-rule smoke workflows.
No production solver or GUI code changed for this packaging correction.
