# WayriCAD 3.1.0

This release adds Quick PI and combines Embed3D, Localizer and Portable Assets into Project Library. The suite now contains 21 separately installable KiCad PCM ZIPs, plus the Python CLI wheel.

## Quick PI

- Native local Net, Mesh and Results views for actual tracks, filled zones, pads, holes and plated vias.
- A 2.5D DC finite-element solver with source voltage, sink current, current/energy checks and explicit mesh refinement.
- Voltage, drop, current density, current arrows, copper/component loss, DC transfer resistance and adiabatic pulse-risk maps, including via hotspots.
- Offline HTML reports with numeric JSON, cancellation and actionable geometry/runtime errors.
- A console with history, engineering notation and pad/net completion. For example, `run pi U1.1 L1.1 5mH+30m L1.2 C1.1` inserts a 5 mH, 30 mΩ series branch between physical copper nets. Multiple branches are supported. Inductance contributes stored energy; this steady-state DC solver does not model AC or switching transients.

## Project Library and existing tools

- One minimal project workflow copies symbols, footprints and models to `local/` by default, or a user-selected project folder, then updates library tables and references. Staging, native validation, backups and restore protect source files.
- Legacy schematic migration preserves instance assignments and power-net semantics; migrated copies support native BOM edits and exports.
- RLC paths now include exact arcs, via transitions and finite-width zone routes around holes/thermal contacts without the former 128-contact cap.
- Return-path checks use filled copper coverage and holes. Heater/magnetics placement rejects occupied copper and same-net shunts. Manufacturing failures retain their DRC details.

## Validation and installation

The [Marble validation record](https://github.com/wayri/WayriCAD/blob/develop/docs/audits/MARBLE_SUITE_SMOKE.md) records actual native operations and numerical results. Full library localization preserves 1,374 nets; a real 5 mH + 30 mΩ series PI run reports 35.040172 mV at 1 A with copper/component losses separated. Mesh convergence remains a separate requirement; the full +12V example is not converged.

In KiCad 10, use Plugin and Content Manager → Install from File for an individual `WayriCAD-*-3.1.0-PCM.zip`. Source users can run `python tools/install_suite.py --apply`; existing installations and the retired Localizer/Portable Assets launchers are backed up. Project Library keeps the existing Embed3D package ID for upgrade continuity. Restart KiCad after updating.

Quick PI needs the local native KiCad Python runtime with NumPy, SciPy, VTK and Matplotlib. Dependency installation may require a package index; simulation and visualization run locally. See [compatibility](https://github.com/wayri/WayriCAD/blob/develop/docs/COMPATIBILITY.md) for runtime boundaries. KiCad 11 and complete live IPC acceptance of every tool remain unverified. Missing external CERN model bytes are reported and cannot be reconstructed by localization. Pulse-risk estimates are not certified fuse-opening predictions.
