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


## Visual workbench revision

The initial overview is superseded by a worksheet-first WebView shell styled consistently with BOM Studio. This is a functional editor: direct worksheet cells, all 34 rule forms, visual condition-builder handoff, enable/disable, duplication/deletion/priority, undo/redo, symmetric matrix compilation, six parameterised set families, netclass dimensions, manufacturing floors, A/B offline priority inspection and native-rule/file-diff review. Unknown native clauses survive form edits. Commands reject stale revisions and stage on cloned workspaces before replacing the current state.

Every original specialist page remains reachable through Engineering tools or contextual actions, using the same workspace and undo history. Returning refreshes the visual shell. Embedded-browser failure falls back to the native worksheet. JavaScript replies use asynchronous WebView execution to avoid nested message-loop deadlocks.

Help/F1 remains inside the app. Browser-only help launchers in the active wx tools now use a shared native WebView / wxHTML viewer; Variant Workbench uses a native Tk reference window. Existing embedded help in BOM Studio, Quick PI and Mechanical Check remains available. Only explicitly chosen external reference links may open a browser.

Verification for this revision: 373 tests passed, 11 optional signing tests skipped, 109 subtests passed. The real KiCad wx/WebView fixture test exercised a worksheet cell edit, undo, matrix generation, set navigation, review, native specialist navigation, embedded help and return with no script errors. Local Chromium rendering of the shipped HTML/CSS/JS verified the layout at 1500px and no horizontal document overflow at 1100px. Rendered screenshots use the supplied demonstration snapshot; they are not Windows desktop captures.

Run `tools/smoke_constraint_visual.py --output .validation/constraint-visual-functional.json` with KiCad's Python for the native bridge test. Full host/PCM/DPI, signing and manufacturing acceptance remain separate from these fixture checks.


## Persistent layer routing revision

Layer routing profiles now save native KiCad 10 tuning profiles, netclass assignments and per-layer width/gap rules. The visual page shows the physical stackup, editable references and dimensions, a fixed-gap width estimator, managed profiles and native in-app guidance. Manufacturing floors, ownership, revision and stale-stackup checks protect staging. Unconfigured routing layers may be prohibited. Generated routing rules follow global defaults and precede existing scoped exceptions.

The native router re-evaluates destination-layer width/gap when using netclass/rule sizing; explicit manual sizing remains an override. Profiles work with Studio closed after offline apply/reopen. Existing tracks are not resized. Automatic live stackup monitoring, plane-continuity analysis and qualified time-domain extraction are not claimed.

Native acceptance found and repaired leading-decimal numeric tokens rejected by KiCad's rule lexer. Emission now changes `.2mm` to `0.2mm` only in numeric constraint tokens, preserving comments, quoted expressions and other syntax.

Validation: 386 tests passed, 11 optional signing tests skipped, 123 subtests passed. A real native WebView test exercised calculate/stage/undo. KiCad 10.0.5 DRC verified distinct width and pair-gap limits on top and bottom layers with Studio absent. The project serializer round-trip preserved native profile fields. Mouse-driven interactive via transitions have not been exercised; automatic re-evaluation was checked in official KiCad router source. See the plugin's `docs/LAYER_ROUTING.md` for workflow, limits and Altium/Xpedition design references.


## Multiple protocol instances

Named instances now support explicit net lists with protocol labels, searchable checkbox selection and select/clear-visible actions. CAN1, CAN2, DDR data and Ethernet groups can coexist with independent layer settings. Direct-net scope preserves netclasses and uses native exact-net routing rules; existing-netclass scope remains supported. Membership conflicts, visible native-profile assignment conflicts, missing nets and recognized orphan pair members are checked. Clone clears membership; update/remove share undo and ownership protection.

Validation: 391 tests passed, 11 optional signing tests skipped, 129 subtests passed. Native WebView checkbox/calculate/stage/undo passed. KiCad 10.0.5 DRC verified separate CAN1/CAN2 widths on both outer layers and differential gaps. Chromium rendering passed with no page errors or document overflow at 1100px. Native gap DRC uses a single-item condition, so generated gap rules intentionally do not depend on B being present. Mouse-driven interactive routing remains a separate acceptance gap.
