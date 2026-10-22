# Quick PI backend performance — 22 October 2026

## Scope and environment

Windows, KiCad 10.0.6 native Python 3.11.5, NumPy 2.4.2, SciPy 1.17.1,
VTK 9.6.1. Baseline source: `856924e564b86aeb1daee745b3b5d3da03f39399`.
These are measured saved-file software workflows, not PCB measurements or a
live-editor qualification. No mesh size, material, FEM tolerance, contour
tolerance, connectivity rule or resource budget was loosened.

The public Marble fixture's saved PCB SHA256 is
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
The tested `+3.3P` supply has 348 tracks, 121 pads, six zones, 88 vias and
two plated pads. The unchanged request uses VTK, a manual 2 mm edge, 3.3 V at
`SK1.199`, and a 0.2 A ideal equipotential load on `U54.6`, `U54.11`, `U54.19`,
`U54.28`, `U54.50`, `U54.75`, `U54.100`. The mesh has 71,031 vertices and
79,135 triangles across 12 copper layers. Modeled copper loss is
0.006314364765637482 W in every comparison.

## Changes and measured results

Contour preparation previously projected each edge's own two corners onto
that same edge. Exact cloud identities now remove those two impossible split
candidates before allocating projection arrays. Other nearby vertices retain
the original native coordinates, sorting and tolerance checks.

Successful `run_job` inspect/geometry/mesh/solve responses can now be reused
within the calling process. Keys include the complete canonical request,
resolved PCB identity, full PCB/project/custom-rule content hashes, and the
explicit native-runtime override. Cached values are immutable JSON bytes;
each caller gets a fresh decoded object. The LRU holds at most four entries
and 96 MiB, rejecting single responses above 48 MiB. It stores no native
objects or live-editor state. HTML publication, batch, convergence and other
actions bypass this cache. Source/settings changes miss; failures never enter
it. Cancellation and timeout checks also apply to hits.

| Measurement | Baseline | Optimized | Interpretation |
|---|---:|---:|---|
| Unprofiled meshing, median of two | 3.818 s | 3.375 s | 11.6% shorter meshing stage |
| Unprofiled complete `execute`, median of two | 7.516 s | 7.560 s | No measured overall uncached speedup in this run |
| Production `run_job`, first request / identical repeat | 13.395 s | 0.750 s | 17.8× faster repeat; successful result reuse, not a faster fresh FEM solve |

Scientific imports were preloaded for the direct `execute` comparison. Each
direct run still loads the PCB, extracts copper, meshes and solves. Production
worker timing includes runtime discovery, process startup and JSON exchange.
The repeat includes input hashing and fresh JSON decoding. The source hash
was checked again afterward and remained unchanged.

The initial profiler identified `_conforming_contours` at 6.181 s of a
21.598 s profiled solve; after the change it was 2.973 s of 16.834 s.
Profiler overhead materially exaggerates this Python-loop cost, so these
numbers identify the hotspot and are **not** the claimed end-to-end speedup.

## Equivalence and boundaries

All 12 layers' conforming contour outputs compare exactly against the frozen
baseline. All potentials, current-density/sheet-current arrays, per-cell and
total losses, terminal results, material and conservation evidence compare
exactly between baseline, optimized, uncached-worker and cached-worker runs.
Centroids and thermal evidence of every nonzero-current cell also compare
exactly; no numerical tolerance was needed for these comparisons.

Two baseline-to-baseline runs already produce differing complete mesh hashes:
VTK chooses different equal-quality triangulations in zero-current copper
lands. The same distinction appears after optimization. The benchmark records
full hashes but does not claim bit-identical complete meshes or inactive-cell
thermal budgets. The electrical comparisons above remain exact.

Large responses above the cache limit and changed electrical settings still
require a fresh worker/mesh/solve. This work does not cache intermediate FEM
matrices or keep a persistent native process. The cache disappears when the
caller exits. Source files and model resolution remain authoritative.

## Display worker contract

Optional `include_display_scene` requests reuse the worker's owned board for
JSON display extraction. Inspect's `display_nets: "default"` uses the first
`+`, `VCC` or `VDD` net, matching the window's choice. Analysis defaults to
its exact geometry net(s); explicit `display_nets: null` requests full board
context. The response contains `board_scene`, `scene_nets` and a scene source
hash, with another PCB content check after extraction. Ordinary CLI requests
receive no display scene. This separates UI responsiveness from FEM timing.

## Checks and reproduction

- 18 cache, worker dependency and service-boundary tests passed in native
  Python, including content/rule/settings invalidation, source mutation during
  cache lookup and worker completion, cancellation, timeout, result mutation
  isolation, LRU bounds, failure rejection and export bypass.
- 48 native mesh/contact/adaptive/auto-mesh/capacity/plated-slot/multisink tests
  passed before the additional display test. The final 24-test service group
  also passed, including native display scope, a single `LoadBoard` per request,
  JSON serialization and unchanged-source checks.
- Source writes, UI rendering and package/release checks are outside this
  backend benchmark; their evidence is recorded separately.

Use `tools/benchmark_quick_pi.py` with a saved request and a frozen baseline
`mesh.py`. It performs two baseline and two optimized direct runs, compares
contours and electrical fields, and then measures production uncached/cached
requests. It refuses an existing output path or a publication request. Example:

```text
python tools/benchmark_quick_pi.py C:/Projects/Example/request.json C:/Projects/Example/timing.json --baseline-mesh C:/Projects/Example/baseline-mesh.py
```

The benchmark's JSON retains the local request path for reproducibility; review
that path before publishing the raw file. The audit above omits machine paths.
