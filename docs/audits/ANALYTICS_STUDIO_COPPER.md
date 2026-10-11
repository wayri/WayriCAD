# Analytics Studio board and copper validation

2026-10-11, Windows, Python 3.14 / Shapely 2.1.2; independent native
geometry checks used KiCad 10's Python runtime. BOM Studio's displayed name is
now Analytics Studio. Package ID, Python modules, CLI and workspace sidecars
remain compatible with existing installations.

## Measurements

The read-only analysis uses the configured saved PCB and records its SHA-256.
Filled-zone and combined copper areas are polygon unions on each layer. Combined
copper includes supported pads, traces, arcs, via annuli and saved zone fill.
Physical drill openings are deducted. Layer faces are summed across layers;
this sum is not the projected area of the board. Net counts of pads, zones and
vias count physical objects once; per-layer rows count their layer occurrences.
Via transition counts count vias, not electrical routes or connectivity.
Component contact area sums placement-side pad lands minus drills. It is not
measured solder contact or a thermal conductance.

Circles and circular arcs use 128 segments per circle, so curved geometry is
approximate. Saved weakly simple zone contours with zero-width hole bridges are
accepted only when removing the bridges preserves their signed area. Crossing
contours and unsupported pad stacks/drawings remain unknown. Unfilled zones
require a KiCad refill and save; this plugin does not perform or certify a refill.
Known-layer subtotals remain available when complete totals are unknown.

## Evidence

- Synthetic analytical checks cover overlap unions, net/layer separation,
  circular lands and drills, blind/through via spans, cutouts, open outlines,
  unfilled zones, bridged holes, invalid crossings, graphical copper and cache
  invalidation. Pad rotation and centre transforms were checked independently
  against a native KiCad-generated footprint.
- On the saved Marble board, both parsers reported 1,006 footprints and 3,664
  vias. Routed length was 53,278.1838679 mm, agreeing with native KiCad within
  0.000001 mm. Copper-zone count was 110; the native inventory also included one
  non-copper mask zone, which copper analytics excludes.
- Before drill subtraction, each layer's saved filled-contour area sum agreed
  with native KiCad polygon areas within 0.000001 mm². Native area sums are a
  reference for contour interpretation; final plugin areas additionally union
  overlaps and deduct physical openings.
- Marble contains one bottom-side unfilled copper zone. Its affected totals
  correctly remain unknown. Supported front and internal layers still produce
  numerical results. The complete saved board is 44 MB; initial full union
  processing took about two minutes in the local check. Results are cached by
  file-content hash for subsequent exports/views, with a two-snapshot limit.
- Full plugin regressions: 1,269 tests passed, three optional checks skipped.
  The later additions were checked with focused geometry, component analytics
  and export suites. Shared runtime/IPC/jobset tests: 43 passed with 93 subtests.
- Real HTTP/headless-browser checks covered the renamed UI, analytics exports,
  net/reference filtering, unknowns, escaping and light/dark compact tables.

This establishes saved-file analytical and browser behavior. It does not claim
live unsaved-board analytics, DRC acceptance, electrical connectivity, thermal
performance, or a newly published PCM binary.
