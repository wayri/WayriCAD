# Quick PI viewport performance — 23 October 2026

Quick PI now batches saved board geometry, renders physical silkscreen glyphs,
pans a cached image during dragging and indexes exact hover queries. This is a
viewport improvement, not a change to mesh, materials or solver tolerances.

## Measured scope

Windows, KiCad 10.0.6, native Python 3.11.5, NumPy 2.4.2, SciPy 1.17.1 and
VTK 9.6.1. Baseline source: `61d81309874952e9943b102ec8dc63c175ded417`.
Public Marble PCB SHA-256:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
The source PCB hash remained unchanged.

The rendering comparison reuses the same saved +3.3P electrical result and
F.Cu field, with full-board context and a 1200 × 800 Agg canvas. Three trials
were run per implementation. Each redraw trial averages eight shifted-view
full redraws; the table gives medians across trials.

| Operation | Before | After | Speedup |
|---|---:|---:|---:|
| Prepare view | 2.990 s | 0.470 s | 6.4× |
| First raster | 1.006 s | 0.0657 s | 15.3× |
| Full redraw | 0.763 s | 0.0578 s | 13.2× |
| Artists per view | 11,682 | 436 | — |
| Text artists | 524 | 1 scale label | — |

Saved silkscreen is retained as native polygons. The comparison includes the
requested visual simplification: fabrication/courtyard context and invented
centroid labels are removed. It is not an identical-visible-content benchmark.
One-time native scene extraction was 10.014 s before and 9.557 s after; this
remains a startup cost. These numbers do not measure solving or whole-suite
performance.

## Exact hover queries

The saved mesh contains 79,135 cells across 12 layers; this test uses 4,887
F.Cu cells. It queries 100 distributed cell centroids and 100 known empty points.
Selected rows and values match the baseline exactly. Three-trial medians:

| Operation | Before | After |
|---|---:|---:|
| Query-index setup | 10.372 ms | 7.558 ms |
| 200 exact picks | 26.881 ms | 1.090 ms |
| 200 hover events, including simple-Agg rendering | 1.755 s | 0.106 s |

Previously all 200 hover events requested full redraws. Now they cause no full
redraws and 101 changed-tooltip blits. Repeating the same cell or empty point
100 times causes no additional repaint. This is a simple-axes benchmark, not
full-board or native-window frame-rate measurement. The JSON also retains
instrumented hover timings with redraw calls suppressed; those are diagnostic
and are not equivalent workloads for a speedup claim.

## Native interaction and regression checks

A real Quick PI window and wx main event loop were exercised with the same
public saved-board scene. Thirty drag-motion events caused zero full scene
rasterizations during the drag and one exact rasterization on release.
Motion-dispatch timing in the JSON excludes operating-system painting and must
not be interpreted as end-to-end FPS.

- Native UI/render/report suite: **93 tests passed**.
- Shared suite: **511 passed, 90 skipped, 227 subtests passed**.
- Native tests check exact saved reference polygons, hidden fields, pan limits,
  event forwarding, source/load marker roles and scientific report captions.
- Probe tests cover exact containment, nearest-point selection, view-transform
  invalidation, repeated hover, dragging and callback cleanup.

The exercised native backend is the Agg fallback: this installed wx runtime
lacks the optional SVG extension needed by WxAgg. Full WxAgg interaction and
an installed plugin connected to a live PCB Editor were not qualified here.
The test harness injects a saved illustrative result; it does not solve again.

## Screenshot provenance

![Native Quick PI window on Marble](../../quick_pi_plugin/help-native-viewport.png)

Actual native-window capture on the public Marble PCB above. The displayed
result uses an assumed 3.3 V source at SK1.199 and 0.2 A load at U54.6, with a
3.0 V minimum target and a manual 2 mm mesh. Loads/materials are illustrative,
not measured board operating conditions or a mesh-convergence claim. Full-board
context is enabled for this demonstration. Only the public board basename is
shown; no private paths, hostnames or identifiers appear, and no redaction was
needed. Existing screenshots are retained.

[Raw timings and trial data](QUICK_PI_VIEWPORT_PERFORMANCE_2026-10-23.json).
These source changes are not in the existing v3.6.26 binaries.
