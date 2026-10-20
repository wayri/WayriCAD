# Mechanical Check review workspace

The current source simplifies inspection without changing collision algorithms. It follows the published 3.6.20 release and is not included in those installers.

## Changes

- Scrollable setup/report pages and expandable optional comparison/hardware controls.
- Hideable, resizable review sidebar; independently resizable finding list/details.
- Separate Findings, Measure and Display tabs; direct focus and isolation controls.
- Human-field token search, open/waived filters, deterministic sorting and previous/next navigation.
- Camera and selected-finding preservation during sorting; optional manual camera preservation during navigation.
- Part clicks select the first currently visible matching finding. Empty filters and changed boards clear stale finding actions and geometry labels.
- Readable units, maximum/required thresholds, evidence, suggested actions and waiver reasons. Coverage gaps remain incomplete.

## Validation

Windows; KiCad 10.0.6 bundled Python 3.11/wxPython/OpenGL; FreeCAD 1.1.

The Mechanical Check suite ran 105 tests: 101 passed and 4native-outline checks skipped in the system Python environment. New pure review tests verify immutable filtering, search without geometry serialization, threshold units, waiver semantics and coverage summaries. Eleven pure review tests include regional-height and overlap-volume maximum semantics. The shared root suite passed 476 tests, with 88 skipped and 222 subtests passed. All 23 disposable PCM ZIPs passed schema, syntax, independent-runtime, icon and action checks; published archives and the public feed were not changed.

The real native workspace harness ran both Quick 2D and exact 3D modes with the public validation fixture, KiCad extraction/STEP export and FreeCAD solid analysis. It checked orbiting, ray picks, point/edge/center measurements, OpenGL errors, camera preservation, filtering, sidebar toggling, splitters and expanded-rule scrolling at 1024×720. Both source board hashes were unchanged. An extracted Mechanical Check PCM archive also passed the exact 3D workspace harness with package-local imports, including the final deselection cleanup. Exact 3D produced 7 bodies, 2 height findings and 4 proximity warnings; these deliberately failing fixture results are not a passed mechanical audit.

Commands from the repository root:

```text
python -m unittest discover -s mechanical_check_plugin/tests -v
<KiCad Python> tools/check_mechanical_workspace.py --mode quick2d --output-dir <temporary-output>
<KiCad Python> tools/check_mechanical_workspace.py --mode exact3d --output-dir <temporary-output>
python tools/validate_docs.py --source-only
```

## Screenshot provenance

`mechanical_check_plugin/help-review.png` and its identical resources copy show an actual native exact-STEP workspace at 1200×820 (1184×781 client pixels), captured by the native harness. Source: public repository synthetic fixture `mechanical_check_plugin/tests/fixtures/validation-fixture.kicad_pcb`. No user design or machine-specific path is shown; no redaction was needed. Existing screenshots are retained.

## Limits

This is a Windows native-window/saved-board check. Linux/macOS native GUI, every DPI setting, and live-editor navigation were not verified. Underlying clearance, envelope and missing-model limitations remain in the plugin guide. Native 2D outline skips are not passes.
