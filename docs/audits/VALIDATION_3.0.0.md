# WayriCAD 3.0.0 validation record

Validation host: Windows, KiCad 10.0.5; ordinary Python 3.14 for pure tests and KiCad's bundled Python for native tests. The initial baseline audit is separate from this implementation record.

| Check | Evidence |
| --- | --- |
| Root regression suite | 121 passed, 12 runtime-dependent skips and 78 subtests passed with `python -m pytest tests -q`. Includes package contents, IPC contracts, manufacturing gates and reviewed operations. |
| BOM Studio | Full imported suite: 1,157 tests with one optional skip. After final changes: 129 targeted tests passed, including local browser fallback, authentication and workspace settings. |
| Embed3D | Final pure suite: 296 tests, 277 passed and 19 optional/native skips. Actual KiCad 10 native suite plus two new ownership regressions: 23 tests covered successfully. |
| Routing | 17 native KiCad tests passed: real pads, nets, tracks, vias, keepouts, saved-project netclasses, layer transitions, stale plans and operation recovery. |
| Heater and magnetics | Disposable native boards: reviewed geometry did not modify the PCB; apply, undo and redo succeeded for 99 heater items and 63 magnetics items. |
| Independent packages | All 19 PCM archives pass checked-in official PCM/API schemas, payload compilation, ZIP integrity, icon dimensions and SHA-256 verification. |
| Installation | All 19 archives extracted into an isolated plugin directory; repeated installation backed up the previous directories. No existing user plugin installation was replaced in this test. |
| Installed entrypoints | All 18 PCB ActionPlugin entrypoints imported and identified themselves as WayriCAD from isolated installed packages using native KiCad Python. BOM has a separate desktop entrypoint. |
| Installed CLI backends | Harness HTML and heater analysis ran from the isolated Pin Extractor package without relying on sibling plugin folders. |
| Native windows | Sixteen wx tool windows freshly captured on a disposable fixture; routing, heater and magnetics use actual generated geometry. Protocol Composer and Test Point controls were also expanded/collapsed in native wx. |

Schema validity, native entrypoint imports and fake-transport IPC contracts do **not** establish complete live IPC behavior. A private disposable-editor probe received connection-refused responses during its 40-second limit; its owned process was stopped without live mutations. A full live editor IPC run of all tools was not completed. See [compatibility boundaries](../COMPATIBILITY.md).

Variant's final capture was not completed: Tcl could not see its initialization files through this sandbox, despite matching resources being present. Its launcher now detects unusable runtimes before launching.

BOM's web UI was functionally tested but its browser visual smoke was not completed: the installed wx runtime lacked an embedded Edge backend, and browser automation stalled. The implemented authenticated local-browser fallback is covered by tests. No production-board DRC campaign, KiCad 11 runtime or comprehensive high-DPI/platform matrix was tested.
