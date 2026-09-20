# WayriCAD 3.2 validation

Validated on Windows with KiCad 10.0.5. These checks establish their stated scope, not certification of every analysis or operating system.

| Check | Result and scope |
|---|---|
| Root integration tests | 256 passed, 67 native/optional skips, 133 subtests passed |
| Constraint Studio package | 323 passed; 11 optional-signing skips |
| Native Constraint Studio | Worksheet edit, undo, matrix/sets/review, help and layer-routing bridge passed |
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

## Marble scope

The 16-tool smoke run left the supplied project files unchanged. Pin extraction, in-memory bulk-label undo, bounded copper/fanout/stitching previews and protocol rule export passed. Other tools retained explicit limits: missing external 3D models, legacy schematic write blockers, no invented external harness board, no requirement for a heater/coil on Marble, demo manufacturing limits, envelope-only mechanical screening, and limited electrical-model scope.

The RLC frequency screenshot uses `FMC1_LA_33_P`, an 87.124 mm signal route with two vias. Its resistance is **not a power-rail drop measurement**. Missing reference geometry keeps section L/C/Z0 unknown rather than assigning a nominal impedance.

## Rendering regression found and fixed

A successful SI calculation initially concealed a paint failure on a KiCad 10 via. `PCB_VIA.GetWidth` requires a layer argument. The fix is covered by a native test that invokes drawing directly and checks the canvas error state. Refreshed screenshots show the entire route, both terminals and via rings.

## Remaining limits

Full 3D PI is deferred. SI eye results use an explicitly uniform lossless model, not IBIS/compliance. RLC does not solve arbitrary neighboring-conductor proximity. Magnetic FEM is linear and axisymmetric; imported STEP inspection does not provide arbitrary-solid magnetic meshing. Current distribution and magnetic approximations are explained in each tool's help.

The upstream shared-TEMP Windows IPC collision remains. Multi-editor checks use the documented private-TEMP workaround. Native macOS/Linux UI operation and KiCad 11 are not established by these Windows checks; see the compatibility guide and the release's platform CI run.
