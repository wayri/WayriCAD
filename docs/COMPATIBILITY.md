# WayriCAD runtime compatibility



The suite provides KiCad IPC plugin manifests and individual PCM ZIP packages. Metadata acceptance, Python SDK value contracts, native KiCad tests, and live IPC editor acceptance are separate checks. A package passing schema validation does not establish every feature works on every host.



## KiCad 10



The current IPC path uses the official `kicad-python` package and local wxPython UI. Enable KiCad's API server and allow KiCad to create the plugin Python environment. Dependency provisioning can need a package index; after dependencies are present, the UI and the implemented board/project operations run locally.



Source ActionPlugin launches use KiCad's bundled `pcbnew` and wxPython. Selected native checks were run against KiCad **10.0.5**. The standalone facade contract tests use real **kicad-python 0.8** value objects with a fake transport. They verify library/field identifiers, footprint attributes, pad/via/track construction, net names, layer spans, keepout flags, polygon conversion, update acknowledgements and launcher behavior. They do not connect to an editor.



**There has not yet been a complete live IPC transport integration run of all 21 tools.** Two concurrently open disposable KiCad 10.0.5 editors passed exact socket/token and originating-board checks, including five reconnects per editor, when each used a separate temporary directory. On Windows, two editors sharing the same temporary directory reproduced an upstream IPC endpoint collision. See [troubleshooting](TROUBLESHOOTING.md) for the isolated launch workaround. No per-tool live mutation acceptance is implied by that connection test.



## KiCad 11 and later



KiCad 11 removes the legacy SWIG `pcbnew` bindings. WayriCAD's forward path is the IPC entry point and a host API version of at least 10. The current shared desktop bootstrap still requires KiCad 10 native Python for wx and the saved-file engines; therefore a KiCad 11-only installation is not currently supported. It avoids native net-code assumptions and uses net names for IPC operations.



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

| Embed3D over IPC | Opens a separate saved-project window. An isolated native KiCad 10 worker normalizes placed footprints and validates staged libraries/boards; schematic acceptance uses native CLI netlists. Symbols, footprints and available models are copied into a configurable project folder, with transactional relinking and backups. Native normalization remains KiCad 10 dependent. |

| Embed3D completeness | Missing source libraries/models require their original files. Strict mode refuses incomplete localization; explicit partial mode retains unresolved references and reports them. Native footprint geometry and schematic connectivity are checked before publication. |

| Manufacturing release | Saved input bytes, selected profile/jobset and live serialized board are bound to the verification evidence. IPC requires exact saved/live token agreement from `get_as_string`; a mismatch blocks release. No live IPC equality test has yet been completed. |

| Manufacturing metrics | Reads the same saved PCB/project that CLI checks receive. Ordinary track/via metrics and saved minimum-clearance rules are supported. Non-uniform via padstacks are refused; aspect ratio uses full board thickness conservatively. This is not a full pad-hole or fabrication-process audit. |

| Manufacturing outputs | CLI runs in a private project copy. Only outputs inside that copy are included. Jobsets with external output paths do not automatically contribute those external files to a release. |



## Verification evidence



- Runtime IPC/launcher regression suite: nine passing tests using real SDK objects and mocked transport.

- Embed3D IPC capability/CLI-result suite: two passing tests, including refusal of unsupported serialization and rejection of a nominal CLI success without an export artifact.

- Manufacturing gate suite: five passing regressions covering stale profile/jobset/live inputs, mutation of verification sources, exact-byte hashes and preservation of existing archives on failure. The existing eight engineering workbench tests also pass.

- Native manufacturing probe on KiCad 10.0.5: a synthetic saved PCB matched a second native serialization token-for-token; saved track metrics read 0.2 mm correctly. JSON DRC produced its expected report schema and exit code 5 for an intentional violation. `jobset run --help` verified the command-line argument contract; no production jobset or full GUI release workflow was exercised.



Before declaring a specific future host supported, run live IPC open/preview/apply/undo checks on disposable designs for each tool, check stale-preview and failure recovery behavior, and exercise representative project/jobset/model data on that exact KiCad build.



## Electrical analysis runtime



Trace RLC and Signal Integrity use native KiCad 10 filled-polygon geometry through the shared IPC launcher. Their PCM actions open the active saved board in a local analysis window. Save/refill in KiCad and reopen to refresh; live cross-selection is disabled in this saved-board mode. Set `WAYRICAD_KICAD_PYTHON` if automatic native interpreter discovery fails. KiCad 11 native geometry compatibility remains unverified.



## 3.1 Embed3D and Quick PI



Embed3D replaces the three asset launchers with one saved-file workflow. IPC invokes an isolated KiCad 10 native worker for footprint normalization; local library writes are staged, validated and backed up. Legacy schematic copies preserve instance maps and pass native connectivity comparison.



Quick PI uses actual copper polygons, a VTK conforming mesh, NumPy/SciPy DC FEM and local Matplotlib views. Its wx/Agg fallback supports the bundled KiCad wx build without wx.svg. It models layered copper sheets and circular plated barrels; plated slots/backdrills are rejected until modeled accurately. Mesh convergence, AC skin/proximity effects, temperature feedback and certified fuse-opening times are not implied by a successful DC solve. Explicit series R/L values are accepted; steady-state inductance stores energy and contributes no DC voltage drop.



## 3.1.1 runtime isolation



Desktop actions provision dependencies in a private per-user virtual environment based on KiCad 10 Python. Worker processes disable user-site imports and discard foreign Python/Conda environment settings while preserving the invoking KiCad socket and token. A clean Windows KiCad 10.0.5 runtime successfully installed and executed Quick PI without borrowing the developer’s user-site libraries. Windows, Linux and macOS path/discovery branches have automated coverage; native Linux/macOS desktop operation is not yet verified.



BOM Studio serves its packaged navigation script with an explicit JavaScript MIME type and uses per-window WebView profiles. If the native web view fails to initialize, it reports the failure and opens the same local project session in the system browser. This fallback does not upload the project.

