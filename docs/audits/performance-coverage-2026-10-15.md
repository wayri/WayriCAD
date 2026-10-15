# Performance coverage — 15 October 2026

This is a source audit and focused regression record, not a claim that every
plugin has been timed against a running PCB Editor. Active metadata lists 21
independent plugins: 17 IPC launchers and four SWIG launchers. An IPC launcher
can still perform its analysis on a saved native snapshot in a separate process.

## Shared changes and measured scope

`wayricad_runtime.ipc.read_snapshot(board)` bounds repeated IPC reads to one
synchronous operation. Native boards use a no-op context. Reads stay live outside
the context; facade writes invalidate its caches, including rejected writes.
The context is not a board lock and must not span an event loop or user input.

Source fingerprints always fetch fresh bulk protobufs, even within a read scope.
They include nested footprint geometry, zone geometry and board text. Records are
deterministically sorted and length-framed. Preview exclusions apply only to
the supplied top-level objects. Transport failures propagate instead of reusing
an old digest. Native SWIG fingerprint behaviour is unchanged.

| Check | Previous request pattern | New request pattern | Evidence |
|---|---|---|---|
| Selection, classes and repeat enumeration for 2,000 tracks | 4,005 mocked transport calls | 4 calls | `tests/test_ipc_performance.py` |
| Source check for 4,000 tracks | At least 4,000 item bounding-box requests | Six bulk collection requests; no bounding-box requests | Same suite, real SDK value objects with mocked transport |
| 100 selected pads from 20 footprints | Whole-board selection scans in callers | One selection request and one parent request for 20 IDs | Same suite |
| Pin Extractor footprint polling | All footprints, one selection request per footprint | One selection request, no parent or whole-footprint request | Same suite |

These are reproducible request-count checks, not measured live-editor latency
or solver-speed improvements. Tests also cover next-operation freshness, nested
scopes, exceptions, write invalidation, preview exclusions, text/nested-pad
changes and source checks inside an active read scope.

## Plugin-by-plugin source coverage

“Shared source check” below means the plugin uses the common fingerprint path;
it does not establish that its entire workflow is optimized or validated.

| Plugin | Observed entry/work path | Action in this audit | Remaining measurement or limitation |
|---|---|---|---|
| Analytics Studio | `entrypoint.py` starts its application/server; project analytics parse saved files; separate IPC bridge | No per-item facade loop identified in the entry path | Startup parsing, analytics and web/native interaction latency unmeasured |
| Bulk Label Editor | One footprint enumeration plus drawings on refresh; rename preview rebuilds local rows on text changes | No speculative cache added to local preview | Large-table typing and rendering latency unmeasured |
| Copper Balancer | Backend selection scans and effective-netclass lookups | Searchable multi-select layer control; shared scoped-read APIs available | This audit does not certify that workstream or its full-board runtime |
| Embed3D | IPC bridge uses saved-file asset operations; native bridge has local selected-footprint traversal | No IPC cache added to native-only traversal | Parsing, asset scans and native validation latency unmeasured |
| Pin Extractor | Entry selection, 500 ms selection polling, refresh and controller-map selection | Reads only selected footprints through one bulk selection request; selected child pads do not implicitly select parents | Diagram generation and large-table rendering unmeasured |
| Fanout Generator | Selection polling plus headless geometry planning | Poll only selected objects; bound planner reads; shared source check | Connector search cost and live-editor latency depend on geometry |
| Harness Workbench | Entry builds a document workspace; imports board pin documents | No active-board selection loop found at entry | Large multi-board import and diagram latency unmeasured |
| Heater Designer | Generated geometry, placement preflight and reviewed apply lifecycle | Shared source check; no blanket context around user interactions | Placement obstacle checks and thermal solver remain untimed here |
| Manufacturing Readiness | Saved snapshot audit; DRC/jobsets run in subprocesses | No synchronous per-item selection loop found at entry | Audit extraction and external CLI completion times unmeasured |
| Mechanical Check | IPC snapshot launch; geometry extraction and analysis on saved native board | No facade cache applied to native snapshot extraction | STEP export, meshing and collision analysis unmeasured |
| Planar Magnetics | Local calculation/generated geometry and placement preflight | Shared source check; no broad frame-lifetime cache | Field solvers and placement obstacle costs unmeasured |
| Fusion | SWIG runtime; saved/native project import and update | No IPC cache applies | Import, preview, matching and merge latency unmeasured |
| Constraint Studio | Staged saved-project worksheet; local geometry/condition inspection | Legacy selection bridge inspected; no active callsite found requiring this cache | Worksheet load, inspection and renderer latency unmeasured |
| Quick PI | IPC input UI plus analysis service | Searchable return-net selection, stale-job rejection and batch navigation | This audit does not certify service or solver timings |
| QuickTherm | IPC UI and thermal analysis/report workflows | Multi-component navigation and incremental plot highlights; searchable contacts | This audit does not certify meshing, solve or rendering timings |
| Quick SI | IPC input UI plus path analysis | Cancellable saved-board subprocess, explicit return audit and batch navigation | This audit does not certify analysis or rendering timings |
| Silkscreen Labels | SWIG placement planner and native validation | Native behaviour retained | Placement search and table latency unmeasured |
| Trace RLC / Impedance | IPC selection/path UI and extraction | Visible search for long scalar path inputs; retain scalar terminal semantics | This audit does not certify path-extraction or solve timings |
| Trace Refiner | SWIG refinement planner and preview | Cache pure display geometry; cull and batch visible lines; refresh after Preview/Apply/Undo/Redo | Marble fitted viewport paint 254 → 92 ms in native MemoryDC; planner and snapshot serialization still unmeasured |
| Variant Manager | SWIG project/variant preview and edits | No IPC cache applies | Preview, bulk operations and persistence latency unmeasured |
| Via Stitching | Selection polling, selection bounds and headless grid planning | Read selected items directly; bound planner reads; shared source check | Grid search and native commit latency unmeasured |

Read scopes deliberately end before preview/apply source verification. No cache
persists across user changes, and these changes do not relax routing or design
rule acceptance checks.

## Measured interaction results

Windows, KiCad 10.0.6 bundled Python 3.11; one local machine, single-run
comparisons unless stated otherwise. Times concern the named operations, not
whole-plugin startup or solver accuracy. Public board:
[Marble revision a426777](https://github.com/BerkeleyLab/Marble/tree/a426777d92c0f22a546d4740b419a3937e0c1f90/design),
PCB SHA-256 `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
The PCB remained unchanged.

| Operation | Before | After | Scope |
|---|---:|---:|---|
| Marble sampled return audit | 17.720 s | 0.975 s | 31 tracks, 3 signal vias, 31 filled reference regions, 1,361 return vias; collection adds 0.535 s |
| Search 20,000 long names, 19,000 matches | 3.464 s | 0.151 s | Native list rebuild; two checked rows |
| Clear that search | 2.706 s | 0.137 s | Hidden checks retained |
| Draw 5,000 display polygons including Agg canvas | 1.115 s | 0.061 s | Synthetic scene; 5,000 artists become one collection |
| Marble picking, 20 queries over 193,453 primitives | 1.301 s | 0.0024 s | Warm index; initial index construction adds 0.805 s |
| Trace Refiner fitted Marble preview | 0.254 s | 0.092 s | Median of five native MemoryDC paints; initial geometry capture adds 0.160 s |

Marble display extraction still took 9.675 s. The new pick index does not remove
that initial cost. The Trace Refiner zoomed viewport painted in 0.013 s with
2,133 visible records. These results do not establish equivalent speedups on
every board, OS or plugin.

Quick SI's saved-board worker completed a Marble run in 9.406 s while the native
frame processed 286 heartbeat events. Cancellation stopped the child in 0.407 s;
a timeout cleanup check took 0.109 s. Input changes discard stale output and
invalidate exports. Unsaved live-board analysis retains its explicit synchronous
path. No SWIG objects cross worker threads or processes.

## Search, selection and return-path boundaries

**Find…** is visible beside PI/SI return-net lists, thermal mounting contacts,
the virtual-heatsink reference selector, RLC path inputs and Copper Balancer
layers. Multi-select search preserves checked hidden matches and supports bulk
check/clear of visible matches. Scalar source/receiver fields remain scalar.
Other controls built with the shared readable-choice wrapper support Ctrl+F
and context-menu search; raw wx controls and separate web/native tools have not
all been converted.

Navigation resolves the requested UUIDs/nets before changing selection. It
uses bulk SDK queries, confirms the result and restores the previous selection
on failure. PI offers additive selection; Therm synchronizes multiple component
rows, including footprint parents of selected pads. SI exposes route, return-net
and reverse-selection actions with stale-result guards. SDK transport was mocked
in native frame checks; a running-editor end-to-end navigation test remains open.
Navigation never establishes that saved geometry matches unsaved editor changes.

PI and SI report declared return terminals, sampled reference coverage and nearby
return-via contact evidence. No terminal is invented. Samples use the same local
filled polygon, preserving antipads and disconnected islands. This is geometric
review, not a return-current distribution, return impedance or loop-closure solver.

## Reproduce and remaining work

Run `python tools/benchmark_interactions.py --baseline-ref c60e0ba0` for a
synthetic display comparison. Use KiCad Python and `--board` for a saved public
board; `--output` writes a new JSON file without overwriting evidence. The tool
checks exact picking parity and source hashes. It performs no board writes.

Focused regressions cover IPC freshness/request counts, selection rollback,
search state, rendering parity, SI worker cancellation and stale output, native
Therm multi-selection, PI batch selection, and Trace Refiner preview caching.
Portable root tests and separate PI/Therm physics suites also run; skipped native
tests are not passes. Native frame tests use KiCad Python, not a substitute wx
implementation.

The measured bottlenecks were repeated transport reads, per-item drawing and
list rebuilding. This pass keeps Python interfaces and existing native numerical
libraries; it adds no C++/Rust build or runtime dependency. Fusion, Variant
Manager, external thermal solves and the other unmeasured workflows above still
need representative timing captures before choosing their next optimizations.

## Local validation record

- Portable root suite: 466 passed, 88 skipped, 170 subtests passed (Python 3.14).
- Separate PI physics suite: 224 passed, 25 skipped; Therm: 229 passed, 25 skipped.
- Native SI suite: 76 tests run, one optional-backend skip, no failures.
- Native selection/search/render regression group: 16 tests passed. The PI/Therm
  stale-job lifecycle check passed in separate native GUI processes.
- Native Trace Refiner suite: 38 tests passed; isolated PCM preview, native DRC,
  Apply/Undo/Redo and frame construction passed.
- All 21 candidate PCM archives passed official schema, syntax, assets, icon,
  independence and hash validation. Source and packaged documentation passed.
- Independent SI PCM worker completed the Marble path and return audit using
  vendored runtime code. The wheel passed isolated CLI/assets/report smoke tests.

Native GUI checks used KiCad Python outside the restricted automation sandbox.
Portable tests used a workspace temporary directory; sandbox temporary-file
permission failures were not counted as product passes. Shared selection tests
also cover multiple SDK text-field identities and missing pad-parent responses.
