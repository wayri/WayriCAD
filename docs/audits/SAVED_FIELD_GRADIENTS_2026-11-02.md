# Saved field gradients

Validated on Windows, Python 3.14.2, NumPy 2.4.2, Matplotlib 3.10.8 and Node
24.14.0. Source base: `d028457382da68b760f449c39b958b89eb6fa839` (v4.0.2
development baseline). This is a source fix; published packages are unchanged.

## Behavior

- Quick PI HTML maps use the viewport's existing triangle projection, native
  color table, selected scale and smooth/cell style. Large reports retain that
  style while keeping their existing three-primary-snapshot budget.
- QuickTherm HTML uses a cached gradient texture on supported saved cells,
  clipped by saved board outlines and drills. Layer/time changes invalidate the
  texture; camera changes reuse it. Solver cells remain selectable. Board field
  scales exclude component junction estimates; transient scales stay fixed.
- The read-only saved-results viewer retains explicit PI triangle topology and
  thermal cell edges rather than reducing them to scatter points or flat tiles.
  Sparse unsupported geometry remains samples. Physical layers stay separate.
- Shading is display interpolation only. Numerical arrays, exact probe values,
  unknown cells, source custody and read-only behavior are preserved. No solver,
  geometry write, IPC registration or KiCad-version-specific API was changed.

## Checks performed

- `python -m unittest discover -s tests -q`: 754 tests, OK; 156 skipped.
- `python -m pytest tests -q --maxfail=1`: 941 passed, 161 skipped,
  514 subtests passed. This includes all independent PCM archive schema and menu
  registration checks.
- `python -m pytest quick_therm_plugin/tests -q --maxfail=1`: 280 passed,
  29 skipped, 221 subtests passed.
- Focused shared pixels, interactive plots, saved native renderer and PI export:
  42 passed, 1 skipped, 3 subtests passed. After the final bounded-memory scale
  scan adjustment, saved-viewer tests were rerun: 27 passed, 1 skipped.
- PI report and capacity tests plus thermal exported-control tests: 36 passed,
  13 subtests passed in the initial focused run. Four additional PI export
  contract tests passed (3 subtests).
- Headless Chrome rendered synthetic PI and thermal HTML. Browser assertions
  checked continuous colors, field scales and switching between smooth and raw
  thermal cells. The generated screenshot was visually inspected.
- Task-local PI and thermal PCM archives included the shared renderer and
  imported their affected report modules in isolated Python subprocesses.
- `python tools/validate_docs.py --source-only` and `git diff --check`: passed.

## Limits and outstanding checks

The broader PI suite reached 548 passed, 70 skipped and 497 subtests before
stopping at an existing native inspector fixture missing `metric_summary` in
`test_ui_field_style.py`. A separate existing differential UI fixture fails when
wx is present but pcbnew is absent; it was excluded from that run. The mesh test
was excluded as in the portable CI command. A newly exercised via-label report
fixture was completed with explicit drill/plating dimensions for native scale
calculation; no validation requirement was weakened.

The default interpreter initially lacked jsonschema; it was installed only into
task-local test scratch before the successful shared gate. The all-inventory
candidate validator rejects a two-package directory by design; the full shared
pytest gate subsequently validated all source packages instead.

No running KiCad 10 or 11 editor workflow was exercised: the user's desktop was
reserved for other work. Native rendering was checked with Matplotlib Agg, not
claimed as installed editor acceptance. No release, public PCM feed or installed
plugin directory was modified. Local synthetic HTML, screenshot, browser profile,
test dependencies and candidate ZIPs remain in the isolated task's validation
directory; no shared cleanup was performed.
