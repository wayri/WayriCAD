# WayriCAD Layer Counter

<img src="icon.png" width="64" alt="Layer Counter icon">

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#get-started) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run layer-counter -- --help` |

CLI scope: Counter preview and separate candidate output. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

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

## Implemented methods and research basis

The complete planner and transaction are in [core.py](core.py), with native UI
coverage in [test_ui.py](tests/test_ui.py) and geometry/transaction coverage in
[test_core.py](tests/test_core.py).

- **Physical layer enumeration.** `board.GetEnabledLayers().CuStack()` is
  enumerated front-to-back starting at L1, so sparse native layer IDs do not
  change printed physical numbers. Core-pair strings must name adjacent
  physical layers, front side first, and cover each selected layer exactly
  once. This is validation of user input, not inference of dielectric cores.
- **Deterministic style geometry.** Row and column are constant-pitch layouts;
  staircase uses `0.6 × pitch` vertical steps and zigzag alternates
  `0.65 × pitch`. Core-pair styles offset the two faces by half a pitch.
  Circle/rectangle/polygon/bar frames are constructed from native copper
  segments or filled polygon shapes. Pitch is a lower bound and is increased
  from text size/stroke so labels through L32 fit. All coordinates and sizes
  are millimetres converted once to KiCad internal units.
- **Measured envelope and zone exclusion.** Native glyph and shape bounding
  boxes, rather than estimated character widths, are unioned and expanded by
  the requested margin. One multilayer rule area sets zone keepout only across
  the selected layer set. It does not exclude tracks or pads.
- **Reviewed mutation.** Planning builds detached text, shapes and rule area;
  source/item fingerprints reject stale commits. Add, Undo and Redo use one
  guarded group transaction with rollback on partial native failures.

These layout patterns are project-specific fabrication aids, not a published
registration-coupon algorithm. The [KiCad 10 PCB Editor
manual](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html) is the normative
background for copper text, enabled stackup layers, groups and zone-only rule
areas; it is not validation of a counter's manufacturability. Tests cover
sparse physical numbering, every style, core-pair rejection, native glyph
bounds, stale state, rollback and exact Undo/Redo in
[test_core.py](tests/test_core.py).

## Command line

```text
python -m layer_counter_plugin.cli board.kicad_pcb --output candidate.kicad_pcb --style row --layers L1,L2
```

Review the separate output board before adopting it. Use KiCad 10's bundled Python for native board operations; `--help` also works without native bindings. Omit `--output` for a read-only JSON preview. Existing board/companion destinations are never overwritten; source `.kicad_pro` and `.kicad_dru` companions are copied under the new board name. Run the command with `--help` for all options.

[Detailed help](HELP.md) · [Offline HTML help](help.html)

## Install and limits

Download the **Layer Counter PCM ZIP** from the latest WayriCAD release
and install it using KiCad Manager's
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
