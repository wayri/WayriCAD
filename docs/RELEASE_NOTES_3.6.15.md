# WayriCAD 3.6.15

This release consolidates the interactive PI, SI and thermal analysis workflows
and improves cursor, probe and camera handling. The suite has 19 independently
installable plugins. All 17 IPC packages advance to 3.6.15; Fusion 0.9.8 and
Variant Manager 0.6.1 retain their existing published packages.

## Analysis workflows

- QuickTherm retains interactive top/bottom and STEP-aware 3D views, numerical
  hover, click probes, sortable component crossselection and transient playback.
  Offline report gestures clear stale cursor readings and handle drag cleanup.
- Quick PI retains board-selected inputs, searchable exact net names and voltage,
  current and loss inspection. Quick SI retains route and sampled eye/step probes.
- Thermal screening includes explicit air, vacuum, forced-air, potting and sealed
  boundary models. Spatial and component RC transients retain declared heat
  capacities, scheduled powers and numerical energy evidence.
- PI/SI net search preserves an exact matching selection and clears unmatched
  choices without assigning another net. SI waveform probes use existing sample
  identities, remain stable on resize and suppress duplicate pins; labels no
  longer overlap. New results clear stale probe/cursor state.
- New interaction regression checks cover cursor and input-selection behavior;
  camera and probe refinements preserve the newer solver and STEP implementations.

## Model limits

These are screening models. Equivalent forced-air and sealed boundaries do not
solve CFD or enclosure heating. STEP geometry does not establish materials or
internal package temperature gradients. Use declared inputs and spatial/time
refinement; numerical convergence alone does not qualify the design. No speed
comparison with Fang is claimed. See [thermal workflows](../quick_therm_plugin/QUICK_THERM_USER_GUIDE.md)
and [analysis interaction validation](audits/ANALYSIS_INTERACTIONS_VALIDATION.md).

Release validation and package evidence are recorded in
[the 3.6.15 audit](audits/RELEASE_3.6.15.md).
