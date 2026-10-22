# Quick-tool responsiveness measurements

Measured on Windows with KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2.
The public Marble board was read without modifying its source. Timing is local
wall time, not a guarantee for other boards or machines. The display benchmark
used the public saved PCB with SHA256
`3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512`.
The separately saved backend fixture and its hash are recorded in its audit.

## Display and interaction

| Operation | Previous | Updated | Scope |
|---|---:|---:|---|
| Native display extraction | 10.30 s / 193,453 primitives | 2.62–2.71 s / 61,282 primitives | Marble `+3.3P`, exact selected-net copper plus component/board context; surrounding copper loads on request |
| Prepare and rasterize front-copper preview | about 0.39 s | about 0.13 s | Previous full-board copper versus the focused rail view; includes different visible copper scope |
| Prepare repeated full-board display paths | about 0.21 s | about 0.10 s | Same visible layer and copper, immutable Matplotlib paths reused; raster time remains about 0.18 s |
| Unchanged native Quick PI redraw dispatch | rebuilt plot | about 0.032 s | A solved Marble example; retains existing artists and viewport, does not include a forced canvas raster |
| Repeated fuzzy query, 10,000 synthetic names | 746 ms | 29.61 ms | Shared search helper; bounded ranked shortlist, not an exhaustive edit-distance search |

[Net selection measurements](NET_SELECTION_PERFORMANCE.md) describe literal,
wildcard and fuzzy semantics, the first-query cost and search limits.

Display extraction now runs in the owned worker. Default scene extraction skips
unrelated copper before native tessellation and serializes only display JSON.
Full surrounding copper is loaded when requested. The native board used by the
Decoupling tab is loaded on demand. Source hashes are checked after extraction;
none of this display geometry is solver input.

Quick PI keeps exact selected-net identities separate from search text. A search
keeps a previously chosen net and solved result. PCB selection expands only
pads on the simulated nets. The dedicated net-selection action replaces the
editor selection with exact net objects across layers. Shared search helpers
also serve Quick SI, QuickTherm and other common pickers; this does not establish
a solver speedup for those tools.

The combined-layer view is a projection. Different-layer fields are rendered
separately and never summed or averaged. Overlap can hide a lower layer; native
click inspection asks which solved layer to inspect. Report probes retain layer
identifiers. Focused views fit the studied copper, while keeping a specifically
inspected saved object visible.

## Solving and repeated requests

The [backend benchmark](QUICK_PI_BACKEND_PERFORMANCE_2026-10-22.md) records
Marble `+3.3P` at 79,135 triangles: a production first request took 13.395 s and
an identical cached repeat took 0.750 s. This is result reuse, not a 17.8-fold
speedup of a new solve. Complete requests and saved board/project/rule hashes
key a 96 MiB, four-entry cache. Each caller receives independent decoded JSON;
changed inputs, cancellation, exports and unsupported actions retain their
worker contracts.

The unprofiled meshing stage improved by 11.6%, while complete direct solves
measured 7.516 s versus 7.560 s. There is no measured overall fresh-solve
speedup in that comparison. An earlier instrumented profile overstated the
end-to-end gain because Python-loop profiler overhead changed. Full contour
outputs and electrical results compare exactly; baseline VTK runs already
vary triangulation of zero-current lands. See the backend audit for the exact
equivalence checks and limits.

## Validation and limits

The display tests check exact net matching, preserved holes and native geometry,
explicit scene-cache invalidation, immutable numerical evidence, combined-layer
cell coverage, zoom retention, changed-metric redraw and search preservation.
Native GUI tests also exercise inspector, workspace, source/sink, batch and
shared control behavior. The public Marble report and native window were
regenerated from a fresh saved-board solve with explicitly assumed source/load
inputs; they are software examples, not measured hardware qualification.

This work does not claim that every plugin or solver is now fast. Native file
loading, meshing, field rendering and large HTML/JSON exports still cost time.
No mesh tolerance, convergence requirement or electrical model was relaxed for
these interaction improvements. C/C++/Rust migration has not been performed.

Final source checks for this batch:

- Shared root suite: 503 passed, 89 skipped, 227 subtests passed.
- Quick PI source suite excluding its VTK-dependent mesh module in Python 3.14:
  330 passed, 42 skipped, 383 subtests passed. That system runtime lacks VTK;
  the native mesh/contact/adaptive/autosizing/slot/multisink selection passed
  48/48 in KiCad's scientific Python, with the service/cache checks recorded
  in the backend audit.
- Native Quick PI/view/board suites: 46/46 passed after the final cache fixes.
- Trace Refiner native backend: 73/73 passed; native UI and UUID compatibility:
  12/12 passed (some UUID coverage also appears in the backend suite).
- Source documentation validation, Python compilation and Git whitespace checks
  passed. These checks are not a new packaged release or a live-editor IPC
  qualification.

Trace Refiner also replaces the native task progress dialog with the generic wx
progress dialog: the native UI test exposed a crash while closing the native
progress dialog after successful validation. The resulting native UI tests cover
validation, Apply/Undo and comparison-view changes. Standalone test launchers
flush their actual results and exit without KiCad/wx DLL shutdown callbacks;
that process-exit workaround exists only in the disposable test harness.
