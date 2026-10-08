# WayriCAD 3.6.11

Update QuickTherm, Quick PI, Quick SI and Trace RLC through the WayriCAD KiCad PCM
repository, or install their independent PCM ZIPs below. Restart KiCad after
updating. Other plugins retain their existing package versions.

QuickTherm now handles rotated plated slots in the multilayer copper/via model.
Reports show the saved board outline, holes and components, top/bottom thermal
overlays, an illustrative 3D view, cursor probes and a sortable component table.
Three embedded plots compare the two board faces and component temperatures.
Bounding-box pruning reduces repeated geometry scans without changing the exact
intersection predicates.

Quick SI can estimate travel time automatically from the saved stackup when a
qualified extraction is unavailable. It shows section impedance and coverage,
local endpoint estimates, cumulative delay and resistance in three plots.
Approximate timing remains separate from extracted impedance. Missing reference,
via and coupling evidence remains visible; zone spreading is still unresolved.
Trace RLC includes the synchronized measurement engine used by Quick SI.
Quick PI shows voltage drop, current density and copper loss plots first, with
additional maps available below.

## Validation

Windows with KiCad 10.0.6: 113 QuickTherm tests passed, two skipped; 59 Quick SI
tests passed, one skipped. Quick PI report regressions passed. Real Marble trace
runs produced automatic timing without manually supplying dielectric values.
The 12-layer thermal solve retained all seven plated slots and 3,852 barrels;
the grid-48 run completed in 196 seconds with a 7.28e-12 W heat-balance residual.
See the [Marble validation record](audits/QUICK_ANALYSIS_MARBLE_FIXES.md).

The thermal inputs are assumed scenarios, not measured board operating values.
The maximum junction change from grid 24 to 48 was 0.301 degrees C; tighter mesh
accuracy is unverified and 165 coarse contact proxies remain flagged. The 3D
report is illustrative rather than STEP geometry. SI results are first-order
screening, not full coupled-pair/via simulation or protocol qualification.
Interactive browser click behavior and native UI operation on other operating
systems have not been newly verified for this release.
