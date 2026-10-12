# Constraint Studio UI simplification

Validated on Windows, 12 October 2026. This is a source UI update; published
3.6.15 binaries and PCM feed are unchanged.

## Behavior

- Full-width worksheet by default. Scope filters, board map and rule inspector
  start hidden and open independently. Their choices survive session rerenders.
- Active scope filters have a visible clear button even with the filter panel hidden.
- Edit rule remains available without opening the inspector. Inline edits, undo,
  staging, exports, offline apply and native recovery retain their contracts.
- Three workflow cards and a compact primary navigation. Specialist editors remain
  under More settings & tools, with the active specialist view automatically visible.
- Width/spacing sketches show declared limits, clearly marked not to scale.
- Larger interactive saved-board map; technical expressions and priority tracing
  expand on demand. Hidden inspector/map panels avoid unnecessary scope calls.
- Numbered routing setup. Layer comparison and saved profiles expand separately;
  diagnostic warning summaries remain visible. Trace cards preserve the common
  width/gap scale, label dimensions and reject absent/invalid pair gaps.

## Checks performed

- `python -m pytest protocol_constraint_composer_plugin/tests -q`: **372 passed**.
  Ran with a PTY because inherited pipe handles in this execution environment
  prevented two subprocess-based tests from launching normally.
- `node protocol_constraint_composer_plugin/tests/test_visual_bridge.cjs`: passed.
- `browser_workspace.cjs`: shipped HTML/JS/CSS in headless Chromium, real model
  snapshot of public workflow_demo, simulated message transport. Verified initial
  hidden panels, toggles, no hidden scope requests, filter clearing, edit dialog,
  search, graphic dimensions/unknown gap, light/dark themes, widths 1600/1100/900/650,
  no document overflow, routing folds retained through a signal-type change,
  and no browser errors. This does not exercise native writes or router behavior.
- KiCad 10 bundled Python, `tools/smoke_constraint_visual.py`: **passed**.
  Native wx/WebView message handshake, inline staged edit, undo, matrix staging,
  sets, review, native tools/help and visible 1452x768 WebView; no JS errors.
  This is a disposable saved-project studio window, not a live routing test.
- JavaScript syntax and documentation checks passed.

## Screenshot provenance

`help-workflow.png` (1600x1100) and `help-rule-panels.png` are rendered directly
from the shipped interface and public workflow_demo model snapshot. The first
shows the default closed panels; the second opens board and rule details. Browser
transport is simulated only for display/interaction checks; the model supplies
rules, counts, saved geometry and conservative condition inspection.

The fixture snapshot's board path was replaced with
`C:/Projects/Example/workflow_demo.kicad_pcb` before rendering. No private project
or workstation path is published. Images were visually inspected. They are not
native KiCad window captures or numerical/DRC qualification evidence.

To repeat the browser check, generate a JSON object with `snapshot` from
`studio_model.snapshot(Workspace.load(public_demo_board))` and `inspection` keyed
by rule index using `studio_model.inspect_scope(workspace, {'rule': index})`.
Use a generic `snapshot.board` path for published captures. Set `SNAPSHOT_JSON`
to that file, `NODE_PATH` to the Playwright modules, and optionally
`BROWSER_EXECUTABLE` and `SCREENSHOT_DIR`, then run:

```text
node protocol_constraint_composer_plugin/tests/browser_workspace.cjs
```

Native GUI acceptance on other operating systems, KiCad versions and DPI settings
has not been established by these checks. Scope matches remain separate from
native DRC and engineering review.
