# Fusion variant destination and guided-flow validation

Windows, KiCad 10.0.6 with bundled Python 3.11.5; portable source tests used
Python 3.14. These are generated disposable projects, not private user boards.

- Fusion portable suite: 247 tests completed, 75 opt-in skips, zero failures.
- Shared suite: 336 passed, 77 skipped, 150 subtests passed.
- Variant destination suite with native opt-in: 7 passed, including existing
  working-variant import with routed layout, new-project separate variant, and
  schematic-only selected-sheet extraction/import. Real KiCad BOM exports showed
  selected 22k/DNP while retained Default remained 10k. Target existing geometry
  and original source bytes were preserved.
- Native CLI import preview/apply: 1 passed, including named target configuration,
  source preservation, retained original target component state and completed
  backup receipt whose project fingerprint matched the pre-apply target.
- Guided GUI: 3 passed; cancellation leaves the setup unchanged, source handling
  survives roundtrip, input changes clear preview, busy state prevents action,
  secondary actions toggle explicitly, and bundled native icons are valid.
- Existing native responsive UI: 3 passed. Existing instance UI: 6 passed.
  Source-picker regression run: 10 passed (7 fixture checks and 3 native UI checks).
- CLI source contracts: 11 passed under source and KiCad Python; help opens
  without a GUI runtime.
- Source documentation and local images validated. Screenshots capture only the
  two generated native windows. The displayed project path was substituted in
  controls with C:/Projects/Example before capture. No desktop background or
  private design is present; PNG files have no added personal metadata.

Named overrides retain Default geometry/connectivity; reports identify that
validation state. Named Footprint substitutions and automatic linked updates of
named imports are refused. PCB-presence changes require schematic-only mode.
Portable CI cannot establish native GUI compatibility on every OS; Linux/macOS
native-window and live editor transaction workflows were not qualified here.
