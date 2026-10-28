# Quick PI 3D speed, Joule setup and illustrated guides

Date: 2026-10-28. Windows, KiCad 10.0.6 / Python 3.11.5, NumPy 2.4.2,
SciPy 1.17.1, installed Gmsh. This is a source update; old release assets were
not replaced. No original or private board was modified.

## Implemented changes

- Inventory/native geometry no longer probes unused SciPy/VTK mesh modules
  before a first saved-board view. Full 3D does not require the planar VTK stack.
- Volume connectivity is converted in bounded NumPy arrays instead of per-node
  Python dictionary lookups and tetrahedron lists. Budgets are checked before
  constructing expanded connectivity. Layer-node electrode candidates are reused.
- Repeated-vertex tests, disjoint ideal electrode contraction, undirected graph
  assembly and output conversion are vectorized. Graph stores six undirected
  edges per tetrahedron instead of both directions. FEM equations, material law,
  mesher algorithm, input edge targets and acceptance tolerances are unchanged.
- Volume current-density preparation uses one vector norm operation rather than
  one NumPy function call per cell. Complete output, finite/floating semantics
  and the 5,000-cell deterministic display sample remain unchanged.
- The Joule checkbox opens a scrollable Materials + cooling page, carrying the
  selected net/source/loads. Required unknown physical inputs stay blank; the
  advanced JSON is the same model, not a hidden competing configuration.
- Coupled saved-board preparation reuses the already owned native board rather
  than parsing it twice, and uses the normal ideal grouped-pad resolver. Invalid
  3D/package/constant-power/series combinations are rejected with actionable text.

## Measured evidence

The old implementation was loaded from Git in the benchmark process. Repeated
controlled solver/view timings share imports; they isolate implementation cost
instead of attributing OS/import cache effects to the algorithm.

| Case | Before | After | Evidence |
|---|---:|---:|---|
| 61,440-tetrahedron / 12,393-node bar solve, median of four | 0.447484 s | 0.357995 s | 20.0% less solve time; same potentials, J and cell power exactly |
| Prepare current-density view of the same field, median of five | 0.080859 s | 0.018177 s | 4.45× faster; same 5,000 selected samples from 61,440 cells |
| Fresh-process Marble saved copper/inventory | 7.988632 s | 6.964976 s | Same 1,374 nets, 5,156 terminals, 44,406 display primitives and source hash |
| Native Marble full-volume mesh, local single run | 10.297325 s | 9.081853 s | Same 33,238 tetrahedra / 12,226 nodes and volume check |

Fresh-process load/mesh runs remain subject to OS file/DLL cache and concurrent
workload; those are local observations, not controlled pure-algorithm speedups.
Initial numerical import time is separate from a solve and was not hidden in
reported cached repeats. Native Gmsh/OCC meshing remains the dominant 3D cost;
this change does not justify a claim of orders-of-magnitude end-to-end speedup.

The analytical bar uses 10 × 2 × 0.07 mm copper. Expected resistance is
0.0012314285714285717 Ω; both implementations returned
0.0012314285712480997 Ω, within 1.47e-10 relative to the analytical value.
Potential/J/power maximum differences were zero; centroid coordinate differences
were at most 1.78e-15 mm. Conservation thresholds were not weakened.

## Board and image provenance

Marble source SHA-256:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
Selected net `Net-(C143-Pad1)`, U36.1 to TP4.1, imposed 1.2 V / 0.2 A,
0.8 mm manual edge, 0.025 mm assumed plating, 100,000-tetrahedron budget.
Both volume implementations returned exactly 0.05762072921512063 Ω. At the
imposed current this is 11.524145843 mV and 2.304829169 mW. This is numerical
conditioning evidence, not measured normal operating load or ampacity.

New native client-area RGB captures, with no image edits or private paths:

- `help-marble-3d-volume.png`: actual solved native volume window. Physical XYZ,
  33,238 cells, 5,000 plotted, current/energy/volume checks. Axis ticks were bounded
  for readability; no artificial thickness exaggeration was introduced.
- `help-joule-guided.png`: real new setup page with Marble contact names and
  explicitly illustrative materials/cooling. It is not a solved temperature.
- `help-white-rabbit-input-review.png`: imported public White Rabbit copper and
  the actual missing-explicit-stackup diagnostic. No default fabrication data
  was silently accepted. Imported SHA-256:
  `44b1f5d7da960c3e474ba1010413b9b5b90a7096610effb15dd55d3d3fda54a1`.

White Rabbit inventory verified DDR_A10 (IC50.M2 to RP17.15), 17 tracks,
14.69009154 mm, zero vias, and ETH_100MHZ.TX_P (CN1.1 to Tr1.16), 14 tracks,
14.60869950 mm, one via. Its import has 12 copper layers but no explicit saved
physical stackup. Instructions require fabrication evidence in a separate
reviewed copy before a conductivity calculation; no R/temperature is fabricated.

## Checks

Native focused checks passed: full 3D analytical/topology/meshing/CLI suite (12),
volume-view suite (3), electrothermal workflow (8), and electrothermal UI (4).
The UI suite includes blank required inputs, guided/advanced round-trip and
invalid-value rejection. Sandbox temporary-file permission failures in the
workflow run passed with normal Windows temp permissions; tests were not weakened.
Worker requirement guards, guide links/images, HTML navigation and full recipe
schemas are checked alongside the final integration.

The expanded guide includes a separate control reference and full bundled AC,
PDN, aggregate/shunt transient, steady Joule and electrothermal transient inputs.
Capacitor placement is documented as proximity/connectivity review, not an
unimplemented coordinate optimizer. PI transient inputs remain explicit lumped
circuits; a whole distributed model is not automatically extracted from the PCB.

## Coupled Marble limitation

The complete `marble-joule.example.json` passes strict input validation, but its
actual native worker run stopped after 14.19 s with the plated-slot thermal-contact
diagnostic. It produced no accepted temperature solution. PI coupling retains a
separate thermal backend that also rejects nonplated holes. QuickTherm geometry
support must not be attributed to this backend. The guide labels this example as
a diagnostic reproduction and separately provides the runnable explicit steady
coupling model. No holes, guard conditions or numerical tolerances were changed.

Final release check: 32 affected native tests passed (24 in the combined run and
all 8 electrothermal workflow tests rerun successfully with normal Windows temp
permissions). The bundled `electrothermal-steady.json` also ran through the real
CLI and wrote HTML/JSON with `status=converged`, `converged=true` and all declared
energy checks satisfied. Its geometry origin is `explicit_model`; this is not a
successful Marble coupled-temperature result.
