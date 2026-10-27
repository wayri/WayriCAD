# WayriCAD Layer Counter

## First use

1. Open a PCB and launch Layer Counter from the PCB Editor toolbar or external plugins menu.
2. Choose a style and check the enabled copper layers. L1, L2, etc. identify physical front-to-back copper layers, regardless of native layer IDs.
3. Enter position, text size, stroke, pitch and zone margin in millimetres.
4. Keep **Lower half of physical stack** for normal midpoint mirroring. On a four-layer board L1/L2 remain normal and L3/L4 are mirrored. The full stack determines the midline even when only some layers are selected. On an odd hypothetical stack, the middle layer remains normal.
5. For a core layout or **Second face of each explicit core pair**, review the physical pairs against your fabrication stackup. Each selected layer must belong to one adjacent pair. No real core/prepreg materials are inferred.
6. Click **Preview**. Colours overlay selected layers; the layer selector isolates one layer. Native copper glyphs preserve their actual mirrored state. Dashed bounds mark the zone-only keepout. Changes invalidate the preview.
7. Click **Add counter**, then close the window. Select the native group and press **M** in KiCad to move it. Before Add, the board is unchanged. The group contains text, style graphics and one multilayer zone-only keepout spanning the complete envelope.
8. Refill zones, run native DRC and inspect copper manufacturing output. Minimum features, board-edge spacing and track/pad crossings remain the designer's responsibility.

## Mirroring choices

- **Lower half of physical stack:** default. L3/L4 mirror on four layers; L4/L5/L6 mirror on six. A layer subset does not move the full-board midline.
- **Bottom copper only (legacy):** mirror only B.Cu.
- **Second face of each explicit core pair:** mirror the second number of each reviewed pair. `L1/L2,L3/L4` mirrors L2 and L4.
- **No mirroring:** all labels remain normal.

Layout and mirroring are independent. Core-pair mirrored positions or overlapping slots do not override the selected text policy. If real cores do not follow the default adjacent pairs, enter the fabrication pairs explicitly. The midpoint is based on front-to-back layer count, not dielectric thickness or geometric Z. It does not establish core construction.

## Style guide

There are 24 layouts and cell frames:

- Horizontal / vertical ladders, staircase and zigzag.
- Two-row bank, serpentine grid and radial fan.
- Circle, square, rectangle, diamond, triangle, pentagon, hexagon and octagon frames.
- Chevron, capsule and double-circle frames.
- Bars, corner brackets, crosshair and ruler markers.
- Mirrored-position core pairs and overlapping core pairs.

Pitch is a minimum and can increase to fit the chosen frame. Native text/shape extents determine the keepout plus the entered margin. All graphics belong to their specific copper layer. The presets are layout aids, not certified registration coupons or a standards-compliance library.

## Command line

```text
python -m layer_counter_plugin.cli board.kicad_pcb --style row --mirror-mode lower-half
python -m layer_counter_plugin.cli board.kicad_pcb --style capsule --layers L2,L3 --output candidate.kicad_pcb
python -m layer_counter_plugin.cli board.kicad_pcb --style core-overlap --mirror-mode core-faces --core-pairs L1/L2,L3/L4
```

Omit --output for a read-only JSON preview. Actual board operations use KiCad 10's bundled Python; --help works without native bindings. --mirror-mode accepts lower-half, bottom-only, core-faces or none. --no-mirror-bottom and --no-mirror mean no mirroring; conflicting flags are rejected.

The CLI writes a separate candidate and never overwrites the source or an existing output. Source project and custom-rule companions are copied under the candidate's name. Review that candidate in native KiCad before adoption.

## Input errors and recovery

- Missing/duplicate core pairs: selected adjacent physical layers must be covered exactly once. Actual material boundaries are not inferred.
- Counter too large: reduce size/pitch only within the fabricator's feature limits, or choose another location. Keepout must cover the full envelope.
- Zone still covers a moved counter: refill zones. The rule area excludes zone fill, not tracks or pads.
- Board/source changed: Preview again. Regenerate after stackup changes or flipping; flipping swaps native copper layers without renumbering the text.
- Undo/Redo: use the guarded controls while the originating board and transaction remain current. External edits can require reopening.

The tool does not assign nets, add soldermask windows, alter stackup or create electrical circuitry. Copper counters are deliberate conductive features; inspect their final manufacturing output.

## Preview provenance

help-preview.png and help-styles.png are off-screen renders from the same native copper-glyph drawing path used by the live window. They are not window screenshots. The first shows the corrected four-layer midpoint convention; the gallery shows all 12 added styles. No private board data, local paths or numerical/pixel edits are included.
