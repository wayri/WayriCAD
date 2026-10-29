# WayriCAD 4.0.0 validation scope

Development checks recorded on Windows, October 29–30, 2026. Source, independent
packages, native windows, saved-board numerics and live editor transactions
are separate evidence classes.

## Board-first workspaces

Native Windows checks use 1280 × 800 windows; canvas sizes are widget pixels,
not a stretched diagram. The PI and thermal comparisons use the same fixture
and tab in the previous source and final layouts.

| Tool | Previous canvas | Final canvas |
|---|---:|---:|
| Quick PI | 724 × 661 | 1248 × 633 |
| QuickTherm | 560 × 447 | 1244 × 560 |
| Quick SI, full production frame | — | 1212 × 516 |
| Quick EMerge | — | 1264 × 549 |

- Minimum-size PI and thermal canvases measure 928 × 433 and 904 × 440.
  Drawer toggles retain inputs, results and dragged widths; Focus restores
  them. Existing big screenshots remain alongside new native captures.
- SI header assertions measure real text and bitmap extents at 980 pixels
  wide. Late-icon sizing and nested-toolbar reflow prevent clipped labels.
  Shared icon/layout/lifecycle checks pass 21 tests in both development wx
  and the native KiCad Python environment.
- EMerge's planar rule-area preview preserves physical aspect ratio while
  reducing excess margins. The fixture ROI grows from about 502 × 251 to
  779 × 389 pixels. It is a copper/port preview, not a FEM field solution.
- Independent native review reproduced a shutdown hang when first native
  board I/O followed wx application creation. The corrected actual SI/RLC
  launcher completes its normal main loop and exits 0 in a fresh process.
  Nine SI workspace/setup assertions pass and the process exits 0 after
  correcting the test fixture's initialization order. No assertions were
  suppressed and no forced process exit was used.

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
- Launch context: 15 regression checks cover two captured editor identities,
  repeated connections, authentication rejection, missing context, runtime
  preparation changing the ambient environment, and native analysis retaining
  its source board and connection pair through the handoff. These are isolated
  connection/launcher tests, not a fresh live two-editor acceptance run. The
  previously recorded Windows server endpoint collision remains a host-side
  limitation with the separate-temporary-directory workaround.
- Setup/result persistence: 73 focused checks passed with 2 optional-native
  skips, followed by 14 passing native KiCad Python checks. Coverage includes
  actual setup Save/Load handlers, all six PI study adapters, shunt-capacitor
  banks, source/sink groups, thermal overrides and IBIS file-change rejection.
  EMerge setup and named-result CLI checks passed 31 tests. Independent review
  reproduced and verified fixes for named-file CLI loading and preventing a
  result from overwriting a declared study input. These checks use disposable
  fixtures and in-process native controls, not live editor acceptance.
