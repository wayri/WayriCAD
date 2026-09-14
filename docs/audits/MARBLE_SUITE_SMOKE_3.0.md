# Marble suite smoke - 2026-09-14

This is scoped functional evidence on Berkeley Lab Marble, not end-to-end UI, live IPC, full-board electrical acceptance or KiCad 11 certification. The board contains **1,006 footprints, 41,044 tracks/vias and 12 copper layers**.

`PASS` means the stated operation completed (including correctly rejected unsafe proposals). `LIMITED` means a useful operation completed with an explicit scope/coverage limitation. `BLOCKED` identifies a failed, cancelled or unfinished operation. Design audit failures are separate from test execution status.

| Plugin | Status | Actual operation and result |
| --- | --- | --- |
| WayriCAD BOM Studio | LIMITED | 25 sheets, 1,003 components. Legacy 20211123-format native-write blockers retained. |
| WayriCAD Bulk Label Editor | PASS | Three actual footprint values changed and undone on an in-memory board; no save. |
| WayriCAD Copper Balancer | PASS | 6x6 mm F.Cu region, max 10 shapes: 42 candidates, 3 accepted shapes, no warnings; 3.31 seconds after regional geometry filtering. No board write. |
| WayriCAD Embed3D | LIMITED | 1,006 footprint inventory; 1,399 model references, 1,380 need attention and 19 external. |
| WayriCAD Extract Pins | PASS | 371 actual J* connector pin/net rows exported. |
| WayriCAD Fanout Generator | PASS | C43 via-in-pad, 0.45/0.2 mm via: both pads correctly rejected for other-net copper clearance. |
| WayriCAD Harness and Cable Workbench | LIMITED | Single-board connector connectivity and local HTML; no invented external harness board. |
| WayriCAD PCB / Foil Heater Designer | LIMITED | Reduced design sized from actual board bounds and thermal model using board thickness; no placement/apply acceptance. |
| WayriCAD Localizer | LIMITED | Bounded PMOD sheet scan against full PCB: 11 footprint dependencies, 5 resolved and 6 missing. Five model references unresolved. |
| WayriCAD Manufacturing Readiness Manager | LIMITED | Actual track/drill/annulus/aspect/layer metrics: default demo profile has 5 FAIL and 1 PASS. Full DRC/jobset not run. |
| WayriCAD Mechanical Check | LIMITED | 1,006 components, 5,272 pads, 1,425 coverage gaps from native extraction. Missing CERN model library prevents comprehensive solid review. |
| WayriCAD PDN and Decoupling Planner | PASS | 5,156 connected pads; 43 rail/decoupling findings. |
| WayriCAD Planar Magnetics & Actuator Workbench | LIMITED | Small two-layer coil model derived from real board bounds; no occupied-copper fit or fabrication claim. |
| WayriCAD Portable Assets | LIMITED | Full project dependency inventory; reports 1,399 unresolved model references, preserving source links. |
| WayriCAD Protocol Constraint Composer | PASS | 229 detected protocol assignments; exported managed rules and verified idempotent merge. |
| WayriCAD Return-Path Auditor | LIMITED | Real signal track/ground via and transition/stub analysis. Reference-plane polygon coverage deliberately excluded. |
| WayriCAD Signal Integrity Advisor | LIMITED | /USB/TxD_OUT U23.42 to U25.8 completed using the shared corrected native route engine. Two via transitions retained; impedance status UNKNOWN with null estimate/error. |
| WayriCAD Test Point Descriptor Extractor | PASS | 28 actual test-point/function rows extracted. |
| WayriCAD Trace RLC / Impedance Analyzer | LIMITED | /USB/TxD_OUT U23.42 to U25.8: 9.6125 mm, 7 tracks, 2 vias and 2 layer changes between F.Cu and B.Cu. Global Z0 remains unknown; no copper movement. |
| WayriCAD Design Variant Workbench | LIMITED | 25 schematic sheets, 2,009 parsed objects; read-only native variant inventory. Tk UI/promotion not certified. |
| WayriCAD Via Stitching | PASS | 4x4 mm GND patch near C43: four candidates correctly rejected (2 outside target copper, 2 footprint collision). |
| WayriCAD Visual Diff | PASS | Native Edge.Cuts SVG HEAD-versus-identical-WORKTREE comparison in disposable Git repo; 264,929-byte self-contained HTML. |

## Reproduce

From the suite root, with the disposable project already copied:

```powershell
python tools/smoke_marble_suite.py --project .validation/marble/Marble/design
python tools/smoke_marble_suite.py --tools copper_balancer_plugin signal_integrity_advisor_plugin
```

The harness runs each tool in a separate KiCad Python worker with a 45-second operation timeout; copper also has a cooperative 25-second preprocessing limit. Cleanup is bounded, applies only to child PIDs started by the harness, and records any failure under that worker directory. Raw logs, PID metadata, JSON exports and per-tool results live in `.validation/marble/suite/`; `summary.json` collects all completed results. These generated artifacts are ignored by Git.

The full-board Localizer scan initially completed in 81.39 seconds, outside the desired small smoke budget. The reproducible test now selects the real PMOD schematic while retaining the complete PCB. The initial full-copper Visual Diff exceeded the bound; the reproducible test uses actual Edge.Cuts native SVG. These narrower tests do not certify full-board processing performance.

The source folder `C:/Projects/Kicad-plugins-dev/3d-interference-check/examples/Marble` is read-only input. Work uses `.validation/marble/Marble/design`; geometry mutations remain in memory or disposable worker output. Each completed harness run hashes copied PCB/schematic/project inputs before/after and verifies every original path recorded in `.validation/marble/source-manifest.json`.

## Validation boundaries

Copper regional filtering passed the bounded preview test in 3.31 seconds. Signal Integrity received the shared corrected measurement adapter and its two-via route rerun passed with appropriately UNKNOWN impedance. The revised SI analysis returns UNKNOWN with null impedance/error for unresolved or nonuniform routes, and does not sum independent single-ended impedances into a claimed differential impedance. Five focused uncertainty regressions and three existing SI tests pass.

The RLC row reports modeled sections only; unknown capacitance/return geometry and via antipad effects remain unresolved. No live IPC or UI acceptance is inferred from these core results.

## Additional real RLC cases

The route-engine validation exported these five cases to `.validation/marble/rlc-engine-results.json`. Values represent modeled sections and actual selected pad connectivity. Partial results and null global Z0 remain explicit. Plane results are conservative region/overlap models, not full electromagnetic solves.

| Net / endpoints | Status | Length (mm) | Tracks / vias / zones | Layers |
| --- | --- | ---: | --- | --- |
| FMC1_LA_33_P  /  P1.G36 to U1.B10 | partial | 87.1239 | 31 / 2 / 0 | F.Cu, In9.Cu |
| /ETH_PHY/MDI0_P  /  J4.11 to U4.28 | partial | 19.8799 | 124 / 0 / 0 | F.Cu |
| +12V  /  R15.2 to R16.2 | partial | 4.9835 | 0 / 0 / 1 | F.Cu |
| /Power/+12VS  /  Q2.1 to Q2.2 | partial | 1.2700 | 0 / 0 / 1 | F.Cu |
| /Power/+12VS  /  C131.1 to Q4.1 | partial | 43.1559 | 1 / 1 / 2 | F.Cu, B.Cu |

## Electrical estimates and UI/package checks

- Covered 0.13 mm sections of `/ETH_PHY/MDI0_P` estimate 54.1179 ohm. The route has 0.075325 ohm DC resistance; reference voids keep the overall result partial.
- `+12V` R15.2 to R16.2: 34.2935 square mm island, 12.8798 square mm reference overlap, 12.274 milliohm corridor resistance, 3.302 nH corridor inductance and 4.8664 pF full-overlap capacitance.
- `/Power/+12VS` Q2.1 to Q2.2: 62.3615 square mm reference overlap and 23.5621 pF. Corridor R/L and full-island C are separate approximations.
- Ground candidates include GND. Embedded PCB data supplies 0.105454 mm dielectric separation, Er 4.5 and 0.035 mm copper for these sections. The separate `marble-stack.txt` lists different manufacturing values; it was not silently substituted. Netclass names are not measured impedance targets.
- Native Trace and SI windows passed saved-board mode, unknown/partial display, stale-result clearing and minimum-size layout checks. See [route and sections](../../trace_impedance_plugin/help-workflow.png), [plane view](../../trace_impedance_plugin/help-marble-plane.png) and [SI unknown result](../../signal_integrity_advisor_plugin/help-marble-unknown.png).
- Both electrical tools were extracted from their independent PCM ZIPs into temporary directories and launched using their bundled native-analysis module. Each measured the real 31-track/two-via FMC route; no repository imports were available to satisfy missing package files.
- CLI `inspect`, `path` and `zone` passed on Marble, including numeric JSON, ground/island inventory and exit code 3 for partial results. Native geometry regressions cover false layer crossings, disconnected terminals, zone holes/islands, via spans, hybrid routes, invalid frequency and invalid impedance dimensions.

The saved-board windows must be reopened after saving/refilling changes in KiCad. They deliberately disable live cross-selection. This isolated-launch evidence does not claim an end-to-end click test of KiCad's PCM installer or IPC transport. Complex bent zone paths, dense automatic zone graphs, trace arcs, thermal-spoke impedance and via antipad capacitance remain outside the model.

Final local verification: 142 root tests passed (36 native/platform skips, 89 subtests), 11 native RLC regressions and 31 native Copper Balancer tests passed. All 22 PCM packages passed official schema, syntax, icon and hash validation; the rebuilt wheel passed isolated CLI/assets checks. Repeated wheel builds now exclude generated build directories to prevent recursive payload growth.
