# WayriCAD 4.1.0

Quick PI keeps series-path editing context for the lifetime of its window and
restores it from saved setup files. Manual paths offer net-aware suggestions,
visible component/pin names replace UUID tokens, and grouped current terminals
are shown explicitly. Reviewed parallel branches can be entered at each series
stage without including unrelated gate/control pins.

- Fixed cross-net source/sink restoration for saved series setups. Closing or
  cancelling the editor retains its draft without running an incomplete path.
- Material/environment defaults preview supported starting values, fill missing
  fields and optionally replace existing values. Material selection retains
  reviewed overrides and populates known supported properties together.
- Saved field views and offline Quick PI/QuickTherm reports retain gradients,
  palettes, scales and unknown regions while probes retain exact saved values.
- HTML/PDF export choices retain numerical JSON and companion HTML. Reports
  document recorded net/path scope, grouped pin numbers, ordered series stages
  and full source paths above plots and tables. Batch PDFs include case reports.

KiCad 10 remains the validated target. Existing KiCad 11 integration is retained
as additional experimental support; this release does not claim a complete
KiCad 11 editor acceptance matrix. No design-writing or solver physics changes
are implied by the workflow improvements. Material defaults are documented
screening assumptions, not properties inferred from a board. Unknown material
properties and unsupported paths remain unknown. Static PDF preserves supported
raster figures and tables; interactive views remain in companion HTML.

[Getting started](../README.md#getting-started) ·
[Thermal materials and default population](THERMAL_MATERIALS.md) ·
[Report export](../wayricad_runtime/REPORTS.md) ·
[Previous release](RELEASE_NOTES_4.0.2.md)
