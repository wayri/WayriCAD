# WayriCAD 4.1.0 release validation

Windows, Python 3.14.2 source checks and KiCad 10.0 native Python 3.11.5.
This release retains the supported KiCad 10 API and existing additional KiCad 11
integration. It does not establish a complete KiCad 11 native editor matrix.

## Workflow fixes

- Series drafts survive Cancel/window close and can be restored from setup/path
  files. Cross-net setup validation no longer applies the single-net sink rule;
  restoration includes the actual other-net sink and every reviewed pin group.
- Manual commands offer context-aware suggestions. Visible pad aliases and
  component references replace UUIDs; private solver identities are unchanged.
- Parallel review supports multi-pad components on the reviewed net pair,
  preserves selected/partial groups, lists included and excluded pins, and keeps
  gate/control pads on other nets outside current electrodes. Fresh same-net
  groups default to all eligible pads with a visible preview; saved choices win.
- Material/environment previews fill supported missing values and optionally
  replace existing ones. Known material properties populate together. Loaded
  overrides, invalid nonempty text and unsupported unknowns remain intact.
- Includes the saved-gradient and net/path-scoped HTML/PDF report fixes recorded
  in the adjacent November 2 audits. No new solver physics is claimed.

## Checks performed

- Shared source pytest: **969 passed, 162 skipped, 525 subtests passed**.
- Portable PI suite: **589 passed, 88 skipped, 508 subtests passed**. Command
  excludes `test_mesh.py` as portable CI does, plus the existing differential and
  field-style native fixtures that require a complete native GUI context.
- Native KiCad 10 grouped-series test exercised real board extraction and meshing,
  grouped Q1 electrodes, rejection of an unrelated gate, and a second grouped Q2
  in parallel. The isolated request/response worker returned unequal branch
  currents summing to the requested 2 A, with energy residual below 1e-6 and both
  source-file hashes unchanged. The existing native interpreter was selected
  explicitly; automatic dependency provisioning is a separate runtime contract.
- Actual hidden KiCad 10 PI controllers saved/loaded a cross-net series setup,
  retained all grouped pins, generated the correct Run request and reopened a
  retained draft. Native dialog layout was measured; initial footer clipping was
  corrected by fitting its minimum client height. No desktop clicks were used.
- Native KiCad 10 defaults/controller suite: **10 tests passed**, including
  preview cancellation with ShowModal patched. Shared material/default checks:
  **21 passed, 2 deselected, 7 subtests passed**.
- Focused series editor/parser/parallel checks passed, including unequal-current
  multi-pad Q1/Q2 models, duplicate pad aliases and rejected gate/owner/reuse/drop
  cases. Five session checks cover source-bound context and display-only aliases.
- All **26 independent PCM ZIPs** passed official schema, syntax, icon,
  entrypoint and hash validation. Full documentation validation included ZIP
  images. Isolated wheel smoke exercised CLI entrypoints, BOM API/assets,
  consolidated numerical exports and mechanical rule exports.
- Earlier report follow-up passed the full remote Windows/Linux/macOS CI matrix.
  Final release publication additionally requires CI success on its exact source
  commit; the public feed is promoted only after referenced assets exist.

## Coverage limits and storage

The stock source interpreter lacks VTK and pcbnew; those missing-native checks
are not passes. A worker's broad preliminary run exposed those known environment
limits before the explicit portable/native split above. Native scientific tests
use KiCad 10's installed bindings. Material tests included a few existing native
window constructions; the new preview and editor tests use hidden windows and
mocked modal responses. No running user's editor was automated. Live editor
integration and a fresh KiCad 11 installation acceptance matrix remain separate.

Independent SWIG package version numbers are retained; suite IPC packages and
Python distribution advance to 4.1.0. Published binaries are immutable. Release
ZIPs and distributions are retained as deliverables; build intermediates and
bounded synthetic evidence remain local. No shared cleanup or removal of
pre-existing work was performed.
