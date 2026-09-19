# Constraint Studio integration

Constraint Studio 0.3.1 now supplies the staged constraint workbench inside WayriCAD's existing protocol-constraints package. The shared IPC launcher locates the open board; Studio loads its saved files using the pure Python engine. No extra SWIG ActionPlugin is registered. This retains the package upgrade identity and avoids another toolbar tool for overlapping functionality.

## Delivered changes

- Visual overview: rule priority list, local-lint counters, changed-file summary and clickable, zoomable scope map with supported rule-area outlines.
- Explicit match / unknown / no-match results using the imported conservative inspection engine. A/B conditions without a second object remain unknown; the map describes the rule condition, not the effective constraint or violations.
- Existing protocol presets feed the staged workspace. The old direct project-rule write is removed. Net names with quotes, backslashes and Unicode round-trip; invalid dimensions and malformed managed-block boundaries are rejected.
- Existing worksheets, BGA wizard, matrices, netclasses, project settings, sets/timing, engineering/team tools and offline help are bundled.
- Review diff, separate export, native DRC and offline apply preserve the source/export distinction. Helpers carry license notices.
- Native navigation events arriving after tree destruction are ignored. Header actions no longer stretch the last button across the row.

## Provenance

The user supplied both source and PCM ZIPs and explicitly authorized inclusion under WayriCAD's GPL-3.0 license on 2026-09-20. All 38 shared PCM/source files matched byte-for-byte. The separately supplied USER_GUIDE.md also matched the source guide. Original delivery notices and archive/module hashes are retained. Attached development instructions were treated as reference material, not as requests to publish, install or run commands.

## Verification

- Original development suite: 356 passed, 11 skipped using Python UTF-8 mode. The skipped cases require unavailable optional `cryptography`. Four initial failures under the Windows default encoding were test-source decoding failures; UTF-8 mode resolved them.
- Integrated engine plus targeted integration/suite regression: 359 passed, 11 skipped, 81 subtests passed. Covers lossless managed-block merge, failed-parse atomicity, literal net names, numeric validation, unknown/disabled/layer scope, unchanged source files on export, apply rejection after external edits and package contents.
- Real KiCad 10 wxPython 4.2.2 window smoke: created the integrated window, populated 20 fixture items, navigated to rule editing, staged through the protocol window and exported a review bundle.
- Native KiCad CLI DRC produced a JSON violations report (exit 5) on the exported fixture and left inputs unchanged. This demonstrates the handoff, not a clean-board result. The sandbox emitted registry/plugin-directory access diagnostics; full host acceptance remains outstanding.

Reproduce the integration checks:

```powershell
python -X utf8 -m pytest -q -p no:cacheprovider protocol_constraint_composer_plugin/tests tests/test_constraint_studio.py tests/test_engineering_workbenches.py tests/test_suite_ux.py tests/test_ipc_plugins.py tests/test_package_contents.py
& 'C:/Program Files/KiCad/10.0/bin/python.exe' tools/smoke_constraint_studio.py --native-drc --output .validation/constraint-studio-smoke.json --screenshot .validation/constraint-studio-overview.png
```

## Remaining scope

The saved-board map is deliberately schematic: it does not render filled copper or solve SI/PI. Complex area outlines are omitted from this map; the existing workspace and KiCad remain available for deeper inspection. Current live-board selection/probing and native effective-rule dialogs are not wired through the IPC adapter. Existing Quick SI, Trace Impedance, Quick PI and manufacturing reports are not automatically converted into constraints; sharing those results needs explicit units, provenance and review semantics.

The next useful integration is an explicit “stage suggested constraint” handoff from those tools, bound to the same board snapshot and supported by conflict review. Full PCM installation, multiple DPI settings, all native geometry/transform operations, team signing and KiCad 11 need separate acceptance. No installed plugins or production boards were changed, and no release was published by this work.
