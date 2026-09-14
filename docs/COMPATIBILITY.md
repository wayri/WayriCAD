# WayriCAD runtime compatibility

The suite provides KiCad IPC plugin manifests and individual PCM ZIP packages. Metadata acceptance, Python SDK value contracts, native KiCad tests, and live IPC editor acceptance are separate checks. A package passing schema validation does not establish every feature works on every host.

## KiCad 10

The current IPC path uses the official `kicad-python` package and local wxPython UI. Enable KiCad's API server and allow KiCad to create the plugin Python environment. Dependency provisioning can need a package index; after dependencies are present, the UI and the implemented board/project operations run locally.

Source ActionPlugin launches use KiCad's bundled `pcbnew` and wxPython. Selected native checks were run against KiCad **10.0.5**. The standalone facade contract tests use real **kicad-python 0.8** value objects with a fake transport. They verify library/field identifiers, footprint attributes, pad/via/track construction, net names, layer spans, keepout flags, polygon conversion, update acknowledgements and launcher behavior. They do not connect to an editor.

**There has not yet been a complete live IPC transport integration run of all 19 tools.** An isolated disposable-editor connection probe was attempted with a private config, temporary directory and PCB. The SDK received connection-refused responses within the 40-second limit; the owned editor was terminated and no live mutation was reached. No per-tool end-to-end IPC acceptance is implied by the manifests. Unsupported APIs fail explicitly rather than reporting a successful operation.

## KiCad 11 and later

KiCad 11 removes the legacy SWIG `pcbnew` bindings. WayriCAD's forward path is the IPC entry point, which does not import SWIG and requires a KiCad host version of at least 10. It avoids native net-code assumptions and uses net names for IPC operations.

**KiCad 11 is unverified.** Forward compatibility here means the IPC architecture and package manifests are prepared for that API; it is not a guarantee of full feature parity or a tested future release. Legacy source ActionPlugins that depend on SWIG cannot supply a KiCad 11 fallback. Changes in KiCad IPC capabilities, SDK dependencies or wxPython packaging can require updates.

## Known feature limits

| Area | Current boundary |
| --- | --- |
| Copper Balancer | The IPC-format action opens a saved-board workflow in native KiCad 10 Python. Copper polygon booleans and floating-net generation require SWIG; this engine is not a KiCad 11 port. Outputs are explicit board copies, not live editor updates. |
| Mechanical Check | The dedicated launcher requires native KiCad Python for extraction and wx/OpenGL viewing, plus FreeCAD Python for exact STEP geometry. The imported IPC action uses saved files; unsaved editor edits must be saved first. Its native engine remains KiCad 10 dependent. |
| Visual Diff | Requires Git and `kicad-cli` for native SVG export; compares read-only Git snapshots and the working tree, then writes an offline HTML report. No live IPC mutation or automatic GitHub service is involved. Future CLI compatibility must be tested on that host. |
| Variant Workbench | Uses a local Tk desktop window. The launcher now initializes Tcl during interpreter selection and reports a missing usable runtime explicitly. This sandbox could not open Tcl initialization files even when matching files existed; the final Variant window was not visually reverified. |
| Fanout/stitching over IPC | Straight, closed Edge.Cuts segments, rectangles and polygons can form islands and cutouts. Open, intersecting, touching, degenerate and curved boundaries are refused where outline safety is required. No guessed curve tessellation is used. Final KiCad DRC is still required. |
| Geometry preview | Pads, straight tracks, vias, polygons and candidates are displayed locally. Curved tracks use bounding envelopes in the shared overview. Conservative obstacle checks are not a replacement for KiCad's full rules engine. |
| Advanced/high-speed fanout | Segmented paths, custom angles, family naming filters and atomic differential breakouts are implemented. Measured skew covers generated traces only. Selected saved-project netclass dimensions are available; impedance, package/via delay, full-channel timing, return-plane continuity and interface compliance are not calculated. Native KiCad 10 tests passed; new live IPC behavior remains unverified. |
| Pin extraction | The IPC facade accesses the current editor board. Legacy standalone paths that call `pcbnew.LoadBoard` require a native KiCad Python runtime; the facade does not silently open or substitute another saved board. |
| Embed3D over IPC | Reads saved designs and produces new copies. Existing footprint archives, saved symbols and model workflows are available. The IPC SDK does not expose native footprint-library normalization or footprint S-expression round trips. The UI selects existing archives and disables legacy live-board/library tools with an explanation. |
| Embed3D validation | IPC uses local `kicad-cli` board/footprint SVG export for parser acceptance, and schematic netlist export for schematic acceptance. It verifies export artifacts exist; it does not claim native footprint round-trip equivalence. Native KiCad 10 source mode retains its native parser/normalizer. |
| Manufacturing release | Saved input bytes, selected profile/jobset and live serialized board are bound to the verification evidence. IPC requires exact saved/live token agreement from `get_as_string`; a mismatch blocks release. No live IPC equality test has yet been completed. |
| Manufacturing metrics | Reads the same saved PCB/project that CLI checks receive. Ordinary track/via metrics and saved minimum-clearance rules are supported. Non-uniform via padstacks are refused; aspect ratio uses full board thickness conservatively. This is not a full pad-hole or fabrication-process audit. |
| Manufacturing outputs | CLI runs in a private project copy. Only outputs inside that copy are included. Jobsets with external output paths do not automatically contribute those external files to a release. |

## Verification evidence

- Runtime IPC/launcher regression suite: nine passing tests using real SDK objects and mocked transport.
- Embed3D IPC capability/CLI-result suite: two passing tests, including refusal of unsupported serialization and rejection of a nominal CLI success without an export artifact.
- Manufacturing gate suite: five passing regressions covering stale profile/jobset/live inputs, mutation of verification sources, exact-byte hashes and preservation of existing archives on failure. The existing eight engineering workbench tests also pass.
- Native manufacturing probe on KiCad 10.0.5: a synthetic saved PCB matched a second native serialization token-for-token; saved track metrics read 0.2 mm correctly. JSON DRC produced its expected report schema and exit code 5 for an intentional violation. `jobset run --help` verified the command-line argument contract; no production jobset or full GUI release workflow was exercised.

Before declaring a specific future host supported, run live IPC open/preview/apply/undo checks on disposable designs for each tool, check stale-preview and failure recovery behavior, and exercise representative project/jobset/model data on that exact KiCad build.
