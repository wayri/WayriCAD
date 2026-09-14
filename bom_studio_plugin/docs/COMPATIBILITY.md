# Current 0.8 release boundaries

The complete PCM package is integrated and tested at the application/contract level. Normal GUI is an out-of-process embedded desktop window, not an in-process dock. Source fields are preserved and a dedicated installed-native-CLI export path exists; this is not full native in-memory editor parity. The new creator writes real symbol/footprint/model files and optional catalogue, but does not register or overwrite existing KiCad library tables. Source geometry is required; no part geometry is invented.

Native KiCad host, actual WebView2/Qt/Cocoa engines, Windows/macOS installers, real IPC focus/cross-selection and native library reload remain unexecuted. KiCad 11 is not certified. Unknown native formats/unsupported constructs keep the existing safety gates. See V8_WORKFLOWS.md and TEST_REPORT.md for current behavior; earlier versioned notes below are historical.

---

> **v0.7 update:** symbol/footprint/model capture, independent catalogue browsing and preview, source-set selection and complete-reference native ZIP export are implemented. See V7_WORKFLOWS.md for current asset behavior; prior “3D omitted” limitations are historical. Real KiCad-host validation is still outstanding.

# Version 0.4 additions

> **0.6 update:** V6_WORKFLOWS.md, CONTROL_TRUST.md, HOST_ACCEPTANCE.md and the current TEST_REPORT.md describe the new persistent catalog, independent variants, review gates and remaining validation boundaries. The material below retains earlier subsystem details; the current update takes precedence where extended.

The optional selection-only adapter targets KiCad 10 and kicad-python 0.8.0. It has synthetic driver/GUI tests, not host validation. Direct schematic IPC is not implemented: native PCB↔schematic cross-selection is a relay dependency. Optional RunAction zoom is unstable and unverified. Native job-set JSON and runner use published KiCad 10 contracts; actual host execution and Windows/macOS shell behavior require validation. Core files, variable and native-write gates below remain unchanged. See V4_WORKFLOWS.md and CLI_REFERENCE.md.

---

# Compatibility and scope

## What “KiCad 10 plugin” means here

The installed package contains a documented IPC-plugin manifest and a Python action launched from PCB Editor. The action starts a local browser workspace. It does not call deprecated `pcbnew`/SWIG, does not use GUI automation, and does not need a live schematic IPC endpoint. It reads saved schematic and project files directly. A saved project may be discovered from inherited PCB IPC context with the optional client; manual root selection remains the fallback.

An IPC plugin action is a launch mechanism; it does not by itself prove the correctness of a file adapter. Native host discovery, external Python configuration, editor parsing/rendering and source-to-PCB propagation need target-host validation.

| Input / operation | Status in 0.4.0 |
|---|---|
| Normal single-root KiCad 10 project, with/without one `top_level_sheets` entry | Supported by the adapter |
| Multiple top-level roots | Selected-root inspection only; no checked output/native sync |
| Hierarchical sheets stored as local files | Supported, including repeated sheet instances |
| Multi-unit symbol instances on the same sheet | Merged into one physical part; conflicts block release |
| Multi-unit components split across different sheets | Duplicate references block release rather than guessing grouping |
| Embedded hierarchical sheets | Open rejected; extract to local files using KiCad first |
| Schematic rule areas | Checked output/native sync blocked because geometry-derived attributes are not evaluated |
| Native per-instance variants / sheet variants | Supported differential fields and the five recognized attribute flags |
| Unknown variant tokens | Checked output/native sync blocked |
| Pre-20260306 variant `in_bom` flags | Inversion handled on read |
| Native source writing | Exact known format 20260306 only; no implicit format migration |
| Reference / UUID editing | Not permitted |
| Symbol replacement, pin remapping, PCB replacement | Not implemented |
| Native BOM presets | Detected, but not converted to WayriCAD export templates |
| Native project field-name defaults | Explicit reviewed registration in `schematic.drawing.field_names`; names/visible/URL metadata only |
| Global Preferences / installed symbol-library enforcement | Not performed; share/import profiles per project |
| Existing symbol custom-field standardization | Previewed project-wide staged schema, including all supported component variants; native sync is separate |
| Variable-bearing property names | Raw keys retained; compound-name aliases resolved for WayriCAD; generated exact `${NAME}` fields use KiCad's linked-value rule |
| Column order/visibility and template sharing | Implemented independently for workspace/export; data-only JSON catalogs |
| XML / industry handoff | Generic `wayricad-bom-1` XML and mapped ERP/assembler CSV; not proprietary CAD exchange, IPC-2581 or ODB++ |
| XLSX/ODS | Snapshot workbooks; no macro/formula execution or arbitrary office-template import |
| Native variant rename / delete | Do in KiCad; not written here |
| Workspace / variant variables | Export-only; native sync blocked while nonempty |
| Project text variables | Staged editing and explicit native sync |
| Every KiCad expression and built-in | Not claimed; nested/escaped/math grammars and unresolved expressions remain visible and fail checks |
| Live editor selection | Optional PCB IPC adapter implemented; native schematic relay and focus remain host-untested |
| Unsaved editor data / direct schematic IPC | Not read or written; no direct schematic adapter |
| Live supplier feeds, PLM, ERP, enterprise permissions | Not implemented |
| Electrical, package, pin-equivalence or qualification approval | Not implemented |

## KiCad 11 approach

The compatibility probe discovers local `kicad-cli --version` and tests actual `sch export bom --help` output for `--variant`. It does not assume that a higher version string means all capabilities are usable. It also does not run KiCad-native exports as a claimed equivalence check; that remains a target-host validation task.

Official IPC documentation describes evolving/headless export capabilities for KiCad 11. This package isolates format parsing, workspace logic, exports, writeback and HTTP transport so a tested native/IPC adapter can be added later. Future unknown schematic versions fail closed for production output and native writes.

Supporting KiCad 11 requires real fixtures, token coverage, host round trips, native CLI output comparison, PCB synchronization tests and explicit new version gates. Installing into an `11.0` folder does not provide those tests or certification.

## Xpedition comparison boundary

This preview provides a serious local BOM-management layer: variants, population matrix, inheritance, checks, templates, sourcing metadata, alternate decision records and release artifacts. It is not a replacement for a mature enterprise design-data-management system.

Missing enterprise capabilities include validated parts-library/supply-chain integrations, enforceable multi-user approvals and access control, concurrent engineering, production PLM/ERP connectors, organization-wide part governance, qualified alternate substitution, and a full native host-validation matrix. The local audit trail is editable data, not a legally signed or tamper-proof approval ledger.


## 0.3 additional boundaries

The direct editor changes existing fields/population, not references or circuit topology. Local `.kicad_mod`/saved-PCB inspection is read-only and scoped to resolved libraries/reference paths; package-name heuristics are not geometry qualification. Supplier XLSX is values-only, not every Excel/report dialect. No live supplier API, scraping crawler or guaranteed page-capture compatibility is claimed. The optional extension parser is fixture-tested only. Old workspace sidecars migrate additively; do not downgrade newly saved workspaces. The v0.3 workflows are in `V3_WORKFLOWS.md`; current additions are in `V4_WORKFLOWS.md` and `TEST_REPORT.md`.


## 0.5 quantitative report compatibility

The new analytics/threshold engines do not broaden native KiCad file-format support. They read the existing committed row model and write separate reports/profiles. No additional native/API version is claimed compatible by introducing these calculations. Bare numeric comparisons can now use declared unit defaults or explicit supported units; the v0.4 documented dimensionless-only limitation is superseded by V5_WORKFLOWS. Unsupported math/range labels remain errors/unknowns.

The server/CLI still require Python 3.10+, a modern browser for GUI, and the optional pinned official SDK only for live selection. No additional analytics runtime dependency, paid service or key is required. XLSX outputs are formula-free snapshots. Historical v2/v3/v4 documentation describes the behavior of those releases; V5_WORKFLOWS is authoritative for the quantitative additions.
