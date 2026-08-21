# KiWay v2.26.0 Release Notes

## Standard RLC Models for the Trace Analyzer

Trace RLC / Impedance Analyzer 0.7.0 replaces first-order parallel-plate math
with published transmission-line models:

- IPC-2141A microstrip characteristic impedance and Hammerstad effective
  permittivity; symmetric stripline when copper planes surround the route.
- Distributed L and C from the telegrapher relations, skin-effect AC conductor
  resistance at the analysis frequency, and propagation delay.
- Topology selection reads the actual board stackup neighbours.
- New **Route Preview** tab renders the measured route layer-by-layer with
  endpoint markers, pan, zoom, scale bar, and hover coordinates.
- New **RLC Model** tab lists every model quantity and plots Z0 across trace
  widths at the current stackup with common 50/90/100 ohm reference targets.
- `scipy` supplies CODATA constants when installed; `numpy` accelerates
  sweeps; both fall back cleanly so headless runtimes keep working.

## Shared Pan/Zoom Preview Canvas

A new shared preview canvas adds antialiased rendering, drag-to-pan,
scroll-to-zoom, double-click fit, adaptive millimetre grid with labels,
scale bar, legend chips, and crosshair coordinate readouts:

- Signal Integrity Advisor draws real routed copper for primary and
  differential mate lanes with per-layer colours and endpoint markers.
- Return-Path Auditor overlays severity-ranked findings on routed geometry
  with vias, legend counts, and zoom controls.
- PDN and Decoupling Planner gains a placement map classifying rails, ground,
  loads, and capacitors, ringing failed pins in red next to severity-coloured
  findings rows.
- Fanout Generator and Via Stitching keep their staged PCB workflow on the
  upgraded canvas renderer.

## Workbench UI Polish

- Every guided header now shows an accent bar, a step-progress indicator,
  completed-step checkmarks, and bold active steps across all thirteen wx
  packages (both standalone and workbench widget flavours).
- Manufacturing Readiness Manager adds a gate meter summarising pass/warn/fail
  after each audit and colours audit rows by status.
- Protocol Constraint Composer shows a detected protocol mix chip strip and a
  Copy Rules action alongside export/apply.

## Package Updates

Extract Pins 2.20.0, Bulk Label Editor 0.7.2, Fanout Generator 0.10.0,
Via Stitching 0.10.0, Test Point Descriptor 0.8.0, Trace RLC 0.7.0,
Signal Integrity Advisor 0.2.0, Harness Workbench 0.5.0, Manufacturing
Readiness 0.2.0, PDN Planner 0.2.0, Protocol Composer 0.2.0, Return-Path
Auditor 0.2.0, Heater Designer 0.1.1, Planar Magnetics 0.2.1.

## Safety

Preview surfaces are read-only; every PCB write still requires an explicit
staged preview followed by Commit. Rule application keeps timestamped backups
and managed-block boundaries.
