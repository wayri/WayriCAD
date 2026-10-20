# WayriCAD Layer Counter

<img src="icon.png" width="64" alt="Layer Counter icon">

Add a movable copper-layer identification group to a KiCad PCB. Choose a pattern, select physical copper layers, preview the result, then add it to the board.

| Setup | Options |
|---|---|
| Pattern | Row, column, staircase, zigzag, circle, square, rectangle, diamond, octagon, bar, mirrored core pairs, overlapping core pairs |
| Layers | Checked selection of the current board's enabled copper layers |
| Dimensions | X/Y position, text size, stroke, pitch and zone margin in mm |
| Core pairs | Explicit physical pairs such as `L1/L2,L3/L4`; no inference of core/prepreg construction |
| Bottom text | Mirrored by default |

## Preview

![Native Layer Counter with a synthetic four-layer board](help-preview.png)

Native KiCad 10 / wx preview of a synthetic four-layer board. No private board data or paths are shown; no redaction was needed.

## Get started

1. Open a PCB and launch **WayriCAD Layer Counter**.
2. Choose a style, layers and dimensions. For core styles, review the explicit layer pairs against your fabrication stackup.
3. Click **Preview**. Changing a setting clears this preview. No copper changes occur yet.
4. Click **Add counter**, then close the window. Select the resulting native group and press **M** to move it in KiCad.
5. Refill zones and run native DRC. Inspect the copper features and mirroring in manufacturing output.

The counter includes one multilayer zone-only keepout spanning the whole counter envelope across its selected copper layers. This keeps the through-stack fabrication counter envelope free of zone fill. These do not prohibit pads or tracks; review crossings and clearances yourself. The preview overlays the selected layers using native copper glyph polygons. Their rotation and mirroring match the board, including mirrored core pairs. Select one layer to inspect its actual glyphs. Own Undo/Redo controls preserve the plugin's guarded transaction workflow.

This is a layout aid, with no certified-standard compliance claim. It does not infer real core/prepreg materials or change the stackup.

## Command line

```text
python -m layer_counter_plugin.cli board.kicad_pcb --output candidate.kicad_pcb --style row --layers L1,L2
```

Review the separate output board before adopting it. Use KiCad 10's bundled Python for native board operations; `--help` also works without native bindings. Omit `--output` for a read-only JSON preview. Existing board/companion destinations are never overwritten; source `.kicad_pro` and `.kicad_dru` companions are copied under the new board name. Run the command with `--help` for all options.

[Detailed help](HELP.md) · [Offline HTML help](help.html)

## Install and limits

This is the 0.1.0 source/candidate plugin; the public PCM feed is unchanged until
publication. Build candidates with `python build_pcm.py --output-dir candidate`
and install `WayriCAD-layer-counter-0.1.0-PCM.zip` using KiCad Manager's
**Plugin and Content Manager → Install from File**, then restart PCB Editor.
The plugin is independent and does not require another WayriCAD tool.

Markers are positive copper text/shapes, with no soldermask windows or electrical
net assignments. Layer selection uses physical front-to-back numbering; selecting
only L2 and L6 retains those numbers. These are common layout presets, not an
IPC-certified coupon library or a validated layer-registration tolerance test.
The core pairs must cover selected adjacent physical layers exactly once; confirm
which adjacent faces are actually a core in your fabricator's stackup. Pitch is a
minimum and grows when needed to fit label frames.

The group can be moved or rotated in KiCad. Do not flip it to the opposite board
face: that changes copper-layer assignment without renumbering the labels.
Regenerate after changing the stackup. Zone-only keepouts do not remove tracks,
pads or existing artwork, and previews do not guarantee a clear placement on an
occupied PCB. Refill zones and run DRC after final placement. Changes elsewhere
invalidate in-window Undo/Redo rather than overwriting those changes. Closing the
window discards its local history; normal editor Undo is not claimed.

[KiCad 10 PCB Editor manual](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html)
describes native copper text, groups and rule-area zone exclusions.


## Resize the workspace and find help

Drag the divider between the scrolling counter settings and the layer preview. Widen the settings area to inspect styles, copper layers and core-pair text before adding a counter.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.
