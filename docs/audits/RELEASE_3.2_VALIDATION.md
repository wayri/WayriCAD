# WayriCAD 3.2 validation

Validated on Windows with KiCad 10.0.5. These checks establish their stated scope, not certification of every analysis or operating system.

| Check | Result and scope |
|---|---|
| Root integration tests | 256 passed, 67 native/optional skips, 133 subtests passed |
| Constraint Studio package | 323 passed; 11 optional-signing skips |
| Native Constraint Studio | Worksheet edit, undo, matrix/sets/review, help and layer-routing bridge passed |
| Native DRC rules | Deliberately violating disposable fixture triggered distinct front/back width and differential-gap rules as expected; not a clean-board claim |
| BOM Studio | 1,180 tests passed, 2 skipped; native three-view workspace and conditioned export preview passed |
| Quick PI | 53 numerical, analytics, console and service tests passed |
| Quick SI | 37 tests passed under native KiCad, including direct via rendering and no paint fallback |
| Trace RLC | 21 native hybrid/stackup/AC tests passed; Marble geometry, linked section selection, 41-point AC plot and stale-result clearing passed |
| Copper Balancer | 34 tests passed under native KiCad; native density/rejection preview captured |
| Mechanical Check | Existing native/FreeCAD pipeline and quick-screen tests passed; no-FreeCAD quick-screen fixture retained explicit incomplete coverage |
| Magnetics | 21 package and 8 existing heater/magnetics tests passed; native circuit/FEM plots and actual FreeCAD STEP volume inspected |
| Two editors, packaged tools | Two owned editors with distinct temporary namespaces; Pin Extractor SVG previews and Fanout plans passed without source overlays |
| Two editors, test-point editing | Review/apply/undo, source-editor selection, stale-review refusal and foreign-editor refusal passed on disposable boards |
| PCM packages | 16 ZIPs: official schemas, entrypoints, icons, payload syntax and SHA-256 validated |
| Isolated wheel | CLI help, merged module imports, nested help/assets and absence of retired root packages checked |
| Documentation | Source links and packaged images validated; screenshots inspected for real rendering, not just successful calculations |
| Native light/dark appearance | PI net/mesh/results/placement, SI route/eye/test-point views and RLC geometry/AC plot inspected; process-local dark appearance asserted, user settings untouched |

## Marble scope

The 16-tool smoke run left the supplied project files unchanged. Pin extraction, in-memory bulk-label undo, bounded copper/fanout/stitching previews and protocol rule export passed. Other tools retained explicit limits: missing external 3D models, legacy schematic write blockers, no invented external harness board, no requirement for a heater/coil on Marble, demo manufacturing limits, envelope-only mechanical screening, and limited electrical-model scope.

The RLC frequency screenshot uses `FMC1_LA_33_P`, an 87.124 mm signal route with two vias. Its resistance is **not a power-rail drop measurement**. Missing reference geometry keeps section L/C/Z0 unknown rather than assigning a nominal impedance.

## Rendering regression found and fixed

A successful SI calculation initially concealed a paint failure on a KiCad 10 via. `PCB_VIA.GetWidth` requires a layer argument. The fix is covered by a native test that invokes drawing directly and checks the canvas error state. Refreshed screenshots show the entire route, both terminals and via rings.

## Remaining limits

Full 3D PI is deferred. SI eye results use an explicitly uniform lossless model, not IBIS/compliance. RLC does not solve arbitrary neighboring-conductor proximity. Magnetic FEM is linear and axisymmetric; imported STEP inspection does not provide arbitrary-solid magnetic meshing. Current distribution and magnetic approximations are explained in each tool's help.

The upstream shared-TEMP Windows IPC collision remains. Multi-editor checks use the documented private-TEMP workaround. Native macOS/Linux UI operation and KiCad 11 are not established by these Windows checks; see the compatibility guide and the release's platform CI run.

## Protocol suite integration

Seventeen portable backend/CLI tests cover profile units, budget boundaries, explicit pair/bus membership, duplicate and reversed routes, same-net rejection, malformed JSON, missing evidence, imported eye failures, escaping and input-file preservation. The native Quick SI package suite passes 38 tests.

On a disposable Marble copy, the native seven-tab window screened `/USB/TxD_OUT` from U23.42 to U25.8 (9.612525 mm). With explicit effective Er 3.2, delay was 0.0573577 ns. UART example budgets were met, while reference coverage (3 of 7 sections) and two layer transitions correctly kept the overall suite INCOMPLETE. An intentionally incomplete LVDS group retained missing-mate/coupled-impedance warnings. Actual route drawing, snapshot addition/removal, budget invalidation, export disabling and stale saved-board refusal passed; the original PCB hash was unchanged. These are workflow checks, not measured channel validation.

A high-DPI capture exposed clipped columns; protocol tables now use DPI-scaled widths, readable check names and a full evidence pane. Check selection cross-selects its route for visual review. See [the protocol guide](../QUICK_SI_PROTOCOL_SUITES.md) and the packaged native screenshot.

## Final corpus-fix integration

The integrated checkout passed 305 repository unittests (67 skipped) and 285 pytest tests (67 skipped, 138 subtests). These runs overlap. Native PI (56), SI (38), manufacturing (8) and focused trace/return/frequency tests (40) passed, together with five isolated affected ZIP checks. See [before/after corpus evidence and remaining limits](KICAD_MONKEY_FIX_FEEDBACK.md). Protocol GUI checks passed in light and confirmed native dark appearance; native CLI route assignments and ordinary-Python suite HTML/JSON export also passed.


## PI numerical verification and convergence

The native scientific-runtime PI suite passes 71 tests, including eight known-answer benchmark cases and CLI/study failure guards. The benchmarks use production meshing and solving: uniform and parallel copper, a series via, the published Elmer beam and resistor operating point, and three radial annuli. Finest annulus resistance error is 0.1023%; vector-current L2 error is 1.8647%. [Reference methods](../PI_REFERENCE_BENCHMARKS.md) and [recorded JSON](PI_REFERENCE_RESULTS.json) distinguish verification from measured validation.

The fixed-input four-level Marble MGTAVCC study reports **NOT_STABLE** at 1%: final drop change 0.573%, preceding change 1.696%, final sheet-loss change 1.098%. The finest result is 2.657125 mV at 1 A; peak current is not certified. [Study JSON](MARBLE_PI_CONVERGENCE.json) retains current/energy checks and both board/geometry hashes. Further refinement hits the mesh budget.

Native light and confirmed dark convergence dialogs display both plots and all seven table columns at 200% DPI. Invalid tolerance is rejected; accepting a result preserves its finest edge; changing current clears the study/result and disables export. A raw-pixel dialog sizing bug discovered during capture was corrected with DPI-aware sizing.


The isolated CLI exposed orientation-sensitive constrained triangulation at the second Marble mesh. A bounded rotated-coordinate Delaunay fallback now preserves exact original coordinates and all contour/hole/manifold/area checks. A regression forces the original attempt to fail and requires this fallback with ear clipping disabled. The actual cached-worker CLI plus HTML export now completes all three requested meshes, reproducing the recorded counts/drops and returning exit 3 for NOT_STABLE. The precise startup-state trigger remains unproven; no tolerance was relaxed. The eight reference cases also pass from an isolated PCM ZIP. Linux CI resistance results agree with this Windows run within 9.1e-8 relative.

## Magnetic extraction and BOM analysis integration

The 33 magnetic tests pass, including reciprocal two-winding FEM, invalid geometry, explicit parasitics, equivalent exports and source-file preservation. Independent filament quadrature gives a 0.1134% mutual-inductance error for the finer tested air-core mesh. Four exported circuits passed nine independent reference checks against KiCad 10's bundled ngspice 46. [Methods and recorded references](../MAGNETICS_VERIFICATION.md) separate circuit correctness from physical model accuracy.

BOM Studio's exact configured IPC Python runtime initially timed out despite successfully fetching its HTML, scripts and project data. Synchronous bridge injection in the WebView load event re-entered native event handling. Guarded asynchronous initialization fixes that failure. Two simultaneous isolated hosts using the configured runtime and sanitized environment each displayed 11 demo rows, all three workspace views, a declared 30 g PCB estimate, the native bridge, and four project-local reports, then exited cleanly. This specifically validates parallel BOM windows; it does not remove KiCad's separate shared-TEMP IPC limitation.

The repository suite at this integration point passes 286 tests and 138 subtests, with 67 dependency-specific skips. These counts overlap earlier runs and are not summed.

The complete BOM regression suite passes 1,189 tests with two optional skips. Six shared SPICE-backend tests cover engine discovery, input bounds, worker errors, native crashes and timeouts; actual KiCad-ngspice DC, loaded-transformer AC, motor and 51-point sweep checks also pass.

Native shared-parts acceptance in the configured BOM IPC runtime reached all 11 assembler cards, opened the shared-library pane, and reviewed one captured part. No JavaScript errors or unhandled rejections were observed; source bytes and global KiCad tables stayed unchanged. Sixteen shared-parts and 72 assembler regressions pass, including a catalogue-publication race that now rejects changed payload bytes before filesystem writes.

Capacitance known-answer and domain-sensitivity checks are recorded in [the electrostatic reference](MAGNETICS_CAPACITANCE_REFERENCE.json). Motor winding, phase-balance and native transient references are recorded [separately](MOTOR_REFERENCE.json). Two simultaneous isolated KiCad-ngspice workers also returned correct independent resistor results.

Final integrated checks at this stage: 293 repository tests and 138 subtests pass (67 dependency-specific skips), 1,211 BOM tests pass (two optional skips), and 52 magnetic/capacitance/motor tests pass, including native KiCad-ngspice execution. The guarded final BOM startup also passed again in two simultaneous isolated configured-runtime windows. These test sets overlap earlier counts.

A final launch audit found magnetics was incorrectly selecting the basic IPC environment, despite declaring scientific dependencies. The launcher now selects a dedicated NumPy/SciPy/Matplotlib profile. The exact new managed runtime was created successfully; a regression verifies the launch/profile contract.

Final exact-profile native acceptance passed for coupled FEM/equivalent review, capacitance extraction and explicit passive-network mapping, 51-point transformer AC and 2,015-point motor transient. Each used the newly selected managed runtime with isolated Python and sanitized environment. Motor actions remained enabled after an actual Review button event and event-loop settling; source-file stale guards and project-local report exports passed. Repository tests now pass 294 cases plus 138 subtests, with 67 dependency-specific skips.
