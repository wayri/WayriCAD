# Fusion 0.9.5 validation

7 October 2026, Windows, KiCad 10.0.6 bundled Python 3.11.5. The Fusion
unit/native-GUI suite ran 195 tests with 55 skipped opt-in or unavailable
workflows and no failures. All 12 opt-in native linked-update fixtures passed;
they cover source
inheritance of Value, MPN, Footprint and routing; target-layout retention with
a compatible 0603-to-1206 replacement; and a reciprocal PCB-only update that
preserves target schematic/project bytes, Value and MPN while importing a moved
source footprint and route. A repeat preview succeeds and a local destination
placement change is rejected. The native mixed-stack fixture keeps a two-layer
bottom component on the four-layer output bottom and confirms full-stack
through vias in both insert and whole-project merge. The first-open preview
regression, issue-choice GUI regressions and 12 opt-in linked-window GUI tests
passed. The 18 independent PCM ZIPs
passed schema, runtime, icon and Python syntax validation. A source wheel
passed isolated CLI imports. These are saved-file and native wx tests; they do
not establish a human-operated KiCad editor launch or all-platform behavior.

# Fusion 0.9.4 beta 1 validation

3 October 2026, Windows, KiCad 10.0.6 bundled Python 3.11.5.

The integrated beta source ran 177 tests: 136 passed,
41 skipped, zero failures/errors. Native association and copper
regressions were enabled. Skips cover other native opt-in workflows, GUI tests
and unavailable official IPC SDK tests; skipped tests are not passes.

The precursor source was additionally tested with the complete native backend
matrix: 151 passed, 25 skipped, zero failures/errors. That included 100 mixed
instances, extraction/insertion, linked updates and workspace creation. The beta
retains those tested functional changes and incorporates the current upstream
CLI action-registration guard and packaged help resources. The final native
regressions exercise those together. A native plotted fixture visibly retained
both imported blocks, tracks, vias and filled zones.

Independent raw KiCad XML verifies PCB association paths. Copper regressions
verify identity/geometry preservation, safe renames and all-or-nothing rejection
of ambiguous changed connections. Original schematic/PCB files remain unchanged.
Manufacturing approval and live editor Update PCB are not established. No
installation, connected IPC transaction or light/dark GUI check was performed.

The precursor's unrelated dirty repository suite had five failures involving
concurrent QuickTherm inventory/icon edits. The beta uses a clean develop-based
worktree; GitHub CI results for its exact release commit are recorded separately.

This work was AI-assisted and verified by automated and native saved-file checks;
it is not an independent human engineering review. Existing projects are not
automatically migrated. The stable public feed and 0.9.3 assets remain unchanged.

Historical reports below describe older versions. Their schematic parity checks
did not independently establish literal UUID association matching; 0.9.4 adds
that independent check and supersedes the old root-prefix assumption.

