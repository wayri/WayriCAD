# Layer Counter 0.1.0 validation

20 October 2026. Windows; KiCad 10.0.6 bundled Python 3.11/wxPython and native
kicad-cli. Source/candidate only; the public release feed is unchanged.

## Implemented

Twelve independently previewed styles generate L1...Ln copper text on the
corresponding enabled physical layers. A native group owns text, copper frames
and one multilayer zone-only keepout spanning the whole counter envelope plus
margin. Native physical stack order is used rather than numeric layer IDs.
Partial selections preserve physical numbering. Core pairs are explicit adjacent
layer pairs, never inferred from dielectric/core/prepreg materials. Default
bottom copper and mirrored core-pair glyphs use native text mirroring. Preview
renders native glyph polygons, including actual mirroring, and can isolate layers.

Preview is read-only. Apply is bound to the original native board and serialized
source state; modified preview geometry is rejected. Group insertion and removal
restore prior state on native failures, including failures after mutation. Local
Undo/Redo refuses unrelated board changes. The CLI previews JSON or exclusively
creates a new candidate board with unchanged project/custom-rule companions.
No source file is overwritten.

## Evidence

| Check | Result |
|---|---|
| Native core/CLI/UI regressions | 16 tests passed in a normal wx event loop; process exited normally |
| Style/stack matrix | Every style on 2-, 6-, and 32-copper-layer stacks; read-only Preview and exact Undo/Redo |
| Physical selection | L2/L6 retain their physical names and correct native copper layers |
| Saved layout object | Save/reopen retains group membership; native group Move shifts all text, outlines and keepout together |
| Native fill | Six actual copper pours refill outside the full counter keepout; interior sampled points stay empty on all six layers while copper remains elsewhere |
| Independent native DRC | Six-layer, 12-style fixture: 72 labels, 12 groups, 12 keepouts; zero violations, zero unconnected items |
| Failure handling | Wrong board, stale board, altered preview, invalid settings/pairs, destination conflicts, and post-mutation Add/Remove failures checked |
| Native window | Preview, Add, Undo/Redo, settings invalidation, per-layer view, mirrored glyph rendering and action board-replacement guard |
| Root regression suite | 466 passed, 88 skipped, 173 subtests passed; skipped native contexts are not passes |
| PCM candidates | All 22 package schemas, independent runtimes, actions, icons and Python syntax validated |
| Independent Layer Counter PCM | Fresh extracted ZIP generated a mirrored-core group; exact Undo/Redo, save/reopen, keepout persistence and native window passed without sibling/source imports |
| Wheel | Isolated CLI imports/help, including wayricad-layer-counter, passed |
| Documentation | Current links, images and catalogue validated |

The captured help-preview.png shows the actual native wx window with a synthetic
four-layer example. All numbers use native glyphs; L4 is mirrored as viewed from
the top. No personal paths, machine identifiers or private board data are present.
No redaction was necessary.

## Limits

This is a positive-copper layout marker, not a certified IPC coupon, electrical
circuit or registration-tolerance measurement. Tracks/pads are allowed by the
zone-only keepout and existing geometry is not automatically cleared. Placement
on an occupied PCB requires native DRC and manufacturing review. Refill zones
after final placement. Do not flip the group across board faces: native layer
swapping does not renumber text. Regenerate after stack changes. No soldermask
openings are generated. Native Linux/macOS windows and KiCad 11 remain unverified.
Normal editor Undo and a real PCB Editor toolbar launch were not tested here;
source/native action dispatch and an independent standalone wx window were tested.

Reference: [KiCad 10 PCB Editor manual](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html),
including native copper graphics and rule-area zone-fill exclusion.
