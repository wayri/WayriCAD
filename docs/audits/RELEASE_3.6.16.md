# WayriCAD 3.6.16 release validation

This release packages Analytics Studio board/copper analytics and the simplified
Constraint Studio interface from tested develop source. Unrelated working-tree
changes were preserved. Published earlier release binaries are not replaced.

Local validation used Windows, Python 3.14 and KiCad 10 native Python:

- Shared/runtime suite: 419 passed, 73 skipped, 164 subtests passed.
- Constraint Studio: 372 passed; native wx/WebView staged editing, undo, matrix,
  sets, review, tools and help smoke passed without JavaScript errors.
- Browser interaction checks cover default-hidden panels, filters, editable rules,
  graphics, routing folds, themes and responsive layouts without document overflow.
- Wheel/source build, isolated wheel smoke, official PCM schema, entrypoint/icon/
  hash validation and documentation checks passed for all 19 packages. New Studio
  assets and the isolated Shapely dependency are included. Known private paths
  were absent from the 17 updated PCM text payloads.
- Analytics regressions and the complete cross-platform matrix are checked by CI
  on the release source commit; local results remain in disposable test logs.
- Analytics copper was compared with independent KiCad saved-board APIs on the
  public Marble board; geometry/model limits remain documented in its audit.

Detailed evidence: [copper analytics](ANALYTICS_STUDIO_COPPER.md) and
[Constraint Studio UI](../../protocol_constraint_composer_plugin/docs/UI_SIMPLIFICATION.md).
GitHub CI must pass for the release source commit before publication; asset hashes
must match local builds before PCM promotion. Fusion 0.9.8 and Variant Manager
0.6.1 retain published ZIP bytes, hashes and download URLs.

Skipped tests are not passes. These checks do not establish every native editor,
operating system, DPI configuration, physical accuracy or manufacturing acceptance.
