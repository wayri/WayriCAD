# Suite workflow reliability checks — 26 October 2026

Candidate: `95e3ab7a` plus local corrections. Checks used Windows, KiCad 10.0.6,
Python 3.11.5 and wxPython 4.2.2. Source runtime tests used Python 3.14.2.
No public release, installed plugin or original user design was changed.
This supplements the [3.6.32 release evidence](RELEASE_3.6.32.md); it does not
establish every workflow or platform works.

## Corrected failures

- The documented QuickTherm component-only CLI calculated successfully but
  crashed during HTML export when `thermal_network: null` reached the summary.
  Missing network, limits and mesh evidence now remain unavailable. The same
  CLI exports HTML/JSON: 1.05 W, four of four scoped components solved. Thermal
  equations were unchanged.
- Assistant selection could arrive before its board preview established a
  coordinate transform. Highlight painting raised AttributeError in a wx
  callback although unittest printed OK; the process exited 1. Drawing now
  waits for the camera. All 21 native Assistant checks exit normally after
  correction; eight highlight regressions also pass.
- Analytics' managed profile now probes `shapely.geometry`, loading the GEOS
  dependency used by copper analysis. Root import alone does not establish
  usable native geometry. All 14 runtime tests pass, including a simulated
  incomplete native-geometry installation.

The independent Analytics ZIP also exposed missing sample projects: sample
launch scripts were shipped but `examples/` was excluded. The builder now
bundles these files; a regression starts all three sample modes from the ZIP.

## Per-tool evidence

All 24 CLI help commands completed in native Python; this only establishes
parser reachability. PASS applies to the named operation. LIMITED retains
missing evidence. Real-board checks used an existing public Marble copy:
1,006 footprints, 41,044 tracks/vias, 12 copper layers. Saved hashes were unchanged.

| Tool | Evidence | Boundary |
|---|---|---|
| Analytics Studio | CLI help; stronger GEOS profile probe | Candidate copper UI/backend checks recorded separately |
| Bulk Label Editor | PASS: three real values apply/undo in memory; window opens twice | No saved write/live transaction |
| Component Arranger | 54 tests pass; one GUI test skipped in discovery | Native DRC/apply/undo covered; live editor not connected |
| Copper Balancer | PASS: bounded 6 × 6 mm F.Cu preview, ten-shape cap; window opens twice | No saved write/manufacturing acceptance |
| Embed3D | LIMITED: model/library inventory | Missing external models remain missing |
| Extract Pins | PASS: J* connector pin/net extraction | Full hierarchy editing not repeated |
| Fanout Generator | PASS: bounded obstacle-aware plan; window opens twice | Rejected candidates retained; no new apply certification |
| Harness and Cable Workbench | LIMITED: connector connectivity/report | External destinations not invented |
| PCB / Foil Heater Designer | LIMITED: board-derived design; native generated review/apply/undo/redo | No occupied-board fit/measured thermal claim |
| Layer Counter | 18 native CLI/core/UI tests pass | Synthetic fixtures, reversible insert/stale rejection |
| Manufacturing Readiness | LIMITED: board metric audit | Fabricator acceptance not implied |
| Mechanical Check | LIMITED: native quick2D extraction/screening | Exact solids, heights, enclosure/access unchecked |
| Planar Magnetics | LIMITED: board-derived coil; native review/apply/undo/redo | No measured magnetics/occupied-board fit |
| Project Fusion | PASS: synthetic schematic preview, publish, exported-netlist verification, stale rejection | Disposable destination; original fixture unchanged; no live apply |
| Constraint Studio | PASS: protocol detection/idempotent rule export | Conditions are not native DRC acceptance |
| Quick PI | CLI help; separate candidate DC/autoload checks | These suite checks do not qualify its DC solver |
| QuickTherm | PASS: real worker/documented HTML/JSON export after correction | Component model; board field unknown; earlier numeric/ZIP checks in release audit |
| Quick SI | LIMITED: routed-net impedance, return-path/testpoint extraction | No full-wave/channel compliance; absent reference polygons retained |
| Silkscreen Label Placer | 171 native/backend/CLI/UI tests pass | Synthetic fixtures; no production alteration |
| Assistant | 21 native UI checks pass after correction | Controlled engine jobs; every downstream tool not invoked |
| Trace RLC / Impedance | LIMITED: two-pad route/layer/via RLC; window opens twice | Idealized model; no copper movement |
| Trace Refiner | 90 native/backend/CLI/UI tests pass | Synthetic native DRC, rollback/undo; no production alteration |
| Variant Manager | 13 backend/native hierarchy/native UI tests pass | Disposable hierarchy, backups/restore/stale checks |
| Via Stitching | PASS: bounded real-board plan; window opens twice | Rejections retained; no new saved application |

## Reproduction and limits

`tools/smoke_native_open.py` opened five tools twice on a synthetic saved fixture;
saved bytes were unchanged. `tools/smoke_generated.py` exercised heater (99 items)
and magnetics (63 items) review/apply/undo/redo on fresh in-memory boards.
`tools/smoke_marble_suite.py` ran fourteen applicable operations: six PASS and
eight LIMITED, no worker blockers. Inspect each worker JSON status: the historic
harness exit code alone does not certify unimplemented tool operations.

Native suites used `python -m unittest discover -s <plugin>/tests -v`.
Variant enabled `VARIANT_NATIVE=1` and `VARIANT_NATIVE_UI=1`; focused Fusion
workspace checks enabled `FUSION_NATIVE_WORKSPACE=1`. Sandbox temp directories
initially denied atomic replacement. Workspace TEMP/TMP resolved that without
application changes. Native Python lacks pytest; no pytest pass is claimed.

Focused post-fix checks passed: runtime setup 14, highlight 8, preview cache 9,
custom probes 3, thermal report budget/export 4 and Assistant native UI 21.
A direct Component Arranger GUI assertion also completed, but its ad hoc process
needed interruption during teardown; it is not counted as another clean pass.

Native IPC actions were not connected to a running editor here. Earlier isolated
ZIP/wheel and platform results remain separate; newly built candidate artifacts
need their own independent-package verification.
