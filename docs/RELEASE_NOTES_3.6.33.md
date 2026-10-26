# WayriCAD 3.6.33

Quick PI adds trace and via copper-melting screening, bottleneck highlights and
individual sink-current control. Quick SI adds a neighbour-trace heat map.
Analytics Studio now analyzes saved copper directly, without requiring a BOM.

- **Quick PI:** temperature-dependent adiabatic copper melting onset/full-melt
  estimates, nominal trace/via melting I²t, ranked local bottleneck regions,
  selection highlights and report tables/maps. Pulse-temperature limits remain
  separate. These estimates do not predict fuse opening, arc extinction or
  certified ampacity; cooling and current redistribution during heating are omitted.
- **Viewer controls:** scroll zooms; Ctrl+scroll over a sink pad changes only its
  demand, with fine/coarse steps based on scroll speed. The existing mesh is
  retained and shared-copper current, voltage and losses are re-solved in the
  background. Ctrl+scroll on other solved copper scales the total load.
- **PI inspection:** a small cursor readout compares before/after current and
  selected/all metrics. Losses and Probe have sortable tables with map/object
  cross-selection and resizable columns.
- **Quick SI:** searchable, selectable nearby-trace map, edge gaps, parallel
  overlap, hover details, HTML/JSON reports and `neighbours` CLI. Map colours
  mean geometric gap. Optional local NEXT uses explicit assumptions; unsupported
  geometry and absent model inputs remain unknown.
- **Analytics Studio:** dedicated Copper & routing view, PCB-only opening,
  per-layer/net/net-layer/zone/contact areas, cancellable worker and exports.
  Marble completed in 59.6 seconds; one invalid/unfilled layer remained unknown.
- **Startup/reports:** Quick PI copper loads on first open; Mechanical Check
  prepares its private OpenGL dependencies. Fixed QuickTherm component-report
  export, early preview highlighting and missing Analytics sample payloads.
- Updated plugin help, CLI catalogue, screenshots and validation evidence.

Marble reports are read-only screening studies. Numerical checks, native UI and
package checks have different scopes; see the [release audit](audits/RELEASE_3.6.33.md)
and [suite workflow audit](audits/SUITE_WORKFLOW_RELIABILITY_2026-10-26.md).
