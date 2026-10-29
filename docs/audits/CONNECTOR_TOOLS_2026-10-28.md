# Pin Extractor connector tools validation

Source update on `develop`, not part of the published 3.6.41 packages.
Validated on Windows with KiCad 10.0.6 / Python 3.11.5 / wxPython 4.2.2.

## What is implemented

- Read-only mating contact reviews from the current board, a separately loaded
  board, or an explicitly proposed copy of the source contact layout.
- Independent top/bottom views, added rotations, X reflections and assembly XY
  offsets. Matching requires reciprocal unique contacts within the tolerance.
- Editable A/B label proposals, existing B-net comparison, literal modifiers,
  safe templates, and bulk pasted-name assignment by exact A pin ID.
- CSV/TSV name lists and explicit pin/name pairs, selectable numbering, individual
  row edits and selected/all-row global, local or hierarchical label copies.
- Physical row/column CSV tables retaining pad identities and missing positions.
- CLI `labels`, `connector-grid` and `connector-mate`, with new-file-only exports.

No board or schematic is modified. Native label objects carry names and anchors,
not connector pin bindings; the user places their anchors on the intended pins
or wires. The planar matcher does not validate keying, mating height, 3D fit or
manufacturer compatibility. An opposite-face preset is not a datasheet rule.

## Evidence

The complete Pin Extractor suite passed **43 tests**, including 38 passing
subtests, with the native label-export opt-in enabled. The checks include:

- Asymmetric mirrored/rotated mating, ambiguous and unmatched contacts,
  sparse physical grids, duplicate/invalid inputs and bounded allocation.
- Quoted CSV, TSV, semicolon input, explicit headers and IDs, numbering,
  modifiers, escaping, fresh UUIDs and all three native label kinds.
- KiCad CLI parse/SVG export of generated schematics containing each label kind.
- Five native UI tests covering the full Pin Extractor page integration,
  paired row edits and cross-selection, stale-source blocking, bulk and selected
  line copies, physical views and atomic pasted-name assignment failures.
- Four saved-board worker checks, including a real native reader launched from
  an IPC-only parent without `LoadBoard`. External reads return JSON and a source
  hash; they do not replace the originating live board adapter.

Existing CLI, tool-dispatch, documentation and plugin-inventory checks passed
28 tests and 24 subtests. The new suite is included in the CI workflow.

Read-only public Marble extraction produced J11's 14-pin **7 × 2** grid and
J12/J13's 12-pin **2 × 6** grids. Top/bottom views preserved every pin ID.
Identity-pose matches covered every contact; those checks do not establish
actual mating-part compatibility. The source SHA-256 remained:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
Local matching for those small connectors took about 0.25–0.34 ms, excluding
board loading and UI construction.

One independently built candidate ZIP passed schema, payload syntax,
source-byte, bundled-guide and isolated native CLI checks. The published feed
and existing release assets were not changed. Packaging scratch is local.

## Clipboard validation boundary

The object stream follows KiCad 10.0.6's
[copyable-only schematic parser](https://github.com/KiCad/kicad-source-mirror/blob/10.0.6/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_parser.cpp).
Native file parsing/export succeeded. Interactive paste into Eeschema was not
verified: both desktop automation entry points failed to initialize with
“failed to write kernel assets: The system cannot find the path specified”.
UI tests verified generated copy payloads through a clipboard test boundary;
they are not a claim of completed external-editor clipboard interaction.

See the [workflow and CLI guide](../../extract_pins_plugin/CONNECTOR_TOOLS.md).
