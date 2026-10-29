# WayriCAD 3.6.46 validation scope

Development checks recorded on Windows, October 29, 2026. Source, independent
packages, native windows, saved-board numerics and live editor transactions
are separate evidence classes.

## Native and numerical checks

- Fanout: 93 focused geometry/selection/CLI regressions and 13 native UI tests
  passed with KiCad 10 Python. New tests include per-bank alternation, rotated
  footprints, partial selection, exposed pads and keepouts. Family classification
  and its UI added 32 focused native checks and an explicit wrapping check.
- Two rotated synthetic 32-pad fanout fixtures had zero baseline DRC findings.
  Each escape candidate had 32 dangling-via findings, no clearance/track/drill
  violations and no unconnected items. Strict no-new-findings therefore fails;
  these are unfinished escape endpoints. No finding was excluded.
- EMerge: 34 native viewport/workbench/state/region tests passed. At 1120 × 780,
  the viewport container changed from 790 × 564 to 1104 × 582 pixels. The new
  screenshot is an opaque native software-rendered fixture preview, not a field
  solution or numerical qualification.
- Shared-return FEM: coincident load electrodes match a combined-demand strip;
  source-local demands retain their current at zero drop. Partial overlap and
  a fully condensed electrode have explicit checks. An independent review
  found no actionable issue in the scoped current/power bookkeeping changes.
- Native saved-board extraction/meshing/solve checked 4 A at the supply contact
  plus 1 A and 2 A on one remote electrode: 7 A total, zero local drop and the
  same copper loss as the 3 A remote reference. Board bytes were unchanged.
- The default development Python run passed 551 PI tests with 84 skips; 12
  failures exposed missing VTK or a usable native plotting import. Rechecking
  the affected mesh and differential-view tests in the existing complete
  managed scientific runtime passed 16 tests with 1 native-view skip. These
  environment-limited failures are not counted as passes.

## Boundaries

No private user PCB was modified or published. Native visual tests use public
or synthetic fixtures. Metadata inference remains unreviewed; uncertain current
roles, gate/control behavior, converter dynamics, physical creepage and material
applicability are not guessed. CI and package checks must pass on the exact
source commit before publication. Public asset hashes and release provenance
are recorded with the published release.

## New-workflow verification

- Reviewed power-tree, CLI protection and insulation-screen regressions pass.
  Independent review reproduced and then verified fixes for duplicate physical
  rail declarations, CLI protection of referenced study files and incomplete
  potential-array coverage. Incomplete field coverage remains UNKNOWN.
- The grouped-series native fixture exercised saved-board extraction, meshing
  and the production FEM: 2 A total and component current, 0.4 W at 0.1 ohm,
  excluded gate pins, unchanged board bytes and an energy error below 1e-10.
- Thermal material library and existing electrothermal/whole-board native UI
  tests passed (21 combined checks; final focused rerun 17 checks). Applied
  fields, provenance and invalidation are checked independently of solving.
- Regenerated public portable examples use the current real saved-board
  producers and retain the exact unchanged included PCB hash. The final new
  workflow/example regression set passed 101 tests with 2 environment skips.
