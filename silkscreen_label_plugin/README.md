# WayriCAD Silkscreen Label Placer

<img src="icon.png" width="64" height="64" alt="Silkscreen Label Placer icon">

Arrange visible reference labels on an open KiCad 10 PCB. Preview checked placements, then apply. Labels that cannot fit safely stay unresolved. This is a separate plugin from Bulk Label Editor, which renames text.

![Native silkscreen placement window](help-workflow.png)

The capture uses a disposable example board. Teal boxes are checked native text envelopes and proposed guide lines; the displayed preview font is illustrative. Gold marks pads and grey marks existing text. Inspect the final native silkscreen and run KiCad DRC before saving.

## Use

1. Select parts or pads in PCB Editor, then open **WayriCAD Silkscreen Label Placer**. Choose **Selected parts / text** or **Whole board**.
2. Click **Preview**. The default arranges visible reference labels on their existing F.SilkS or B.SilkS side. It preserves hidden/locked labels and locked parts.
3. Inspect **Top view** and **Bottom view**. Wheel zooms, dragging pans and **Fit** restores the view. Open **Review details** for unresolved or preserved items.
4. Click **Apply labels**. Only accepted changes are applied. Use this window's **Undo** or **Redo** while it remains open. Changes elsewhere on the board invalidate the preview and undo state; preview again rather than overwriting those edits.
5. Run native DRC, inspect readable references and association lines, then save the board. The plugin does not rename references or update the schematic.

**Options** adds existing visible values or board text already on silkscreen, and adjusts minimum text height, stroke, spacing, search distance (12 mm initially) and the guide-line threshold. Dense placement is automatic: larger labels go first, alternate orientations and fine nearby slots are tested, and spatial indexes keep collision queries local. A progress window supports cancellation without modifying the PCB. Enable **Automatically shrink text when needed** to try the preferred height down to your minimum in the chosen size steps. With automatic sizing off, existing larger text is preserved. The stricter native board text/stroke/clearance floor applies. Hidden fields are not made visible and fabrication-layer fields are not moved onto silkscreen.

### Size, direction and formatting

Open **Options → Size & direction** to set preferred height, minimum automatic height and size step. For example, prefer 1.2 mm, allow a minimum of 0.8 mm and use 0.1 mm steps. Up to 16 heights are tried; stroke scales with automatic size while respecting the native stroke floor. The planner tries larger sizes first; native fabrication floors may raise the effective minimum. Choose horizontal, vertical or both orientations, then choose reading from bottom/right, top/left or either direction. These choices correspond to 0°/90°, 180°/270° or all four orthogonal angles, viewed from the label's own board side. Applied fields have Keep upright disabled to retain the chosen direction; Undo restores it.

Open **Options → Formatting** and click **Add preset** or **Add**. Presets are suggestions to review, not automatic classification:

| Preset | Initial matching pattern | Style |
|---|---|---|
| Test points | Reference `TP*` | Knockout |
| Programming headers | Value `*SWD*,*JTAG*,*ISP*,*ICSP*,*PROG*` | Bold |
| Input connectors | Value `*INPUT*,*POWER_IN*` | Italic |

Edit patterns to match your board, for example references `J1,J4`. Patterns are case insensitive; comma-separated patterns match either entry, while filled Reference, Value and Label text criteria must all match. The first matching rule wins; move a rule **Up** to give it priority. Bold, Italic and Knockout each offer **Keep existing**, **On** and **Off**. Remove a rule to stop using it. Rules apply to the text categories included in the preview, without renaming any text. Styles are not applied when a label cannot be placed safely.

Knockout uses KiCad's native filled text background. Its larger native envelope is included in clearance checks, so fewer labels may fit than with ordinary text. Review planned size, angle and styles under **Review details** before applying.

![Native typography options](help-typography.png)

![Native formatting rules](help-formatting.png)

Distant component labels get a checked straight or single-bend guide path ending just outside the component body. Guides must clear pads, openings, other labels/graphics and board edges. If a distant label cannot get a safe guide, that candidate is rejected. Existing plugin-owned guides are managed as part of repeat placement and undo/redo; unrelated drawing lines are preserved. Disabling guide lines is an explicit option.

![Placement workflow](workflow.svg)

## Dense boards

Dense search is enabled automatically. It uses a clearance-scale grid and footprint-edge slots, tries 0°/90° label orientations, places larger labels first and checks straight or single-bend guides. Spatial indexes keep checks local. Search has per-label candidate and overall time budgets; an exhausted search keeps the original label and reports it as unresolved.

![Actual dense 100-part preview](help-dense.png)

| Native KiCad 10 check | Result |
|---|---|
| Synthetic 100-part grid at 3.4 mm pitch | 100/100 labels placed; zero native DRC violations after Apply, versus 199 before; 1 mm labels were not shrunk |
| Public Marble board, 1,006 footprints | 182 eligible references: 85 safely placed, 83 changes, 63 guide paths, 97 unresolved; approximately 14.3 seconds |
| Marble native DRC comparison | 481 findings before, 479 after; no new violation type/item combinations. Existing board issues remain |

These fixtures do not establish that every label fits every dense board. The unresolved count remains visible; change the allowed search distance or review those labels manually rather than reducing fabrication minimums. [Detailed validation](../docs/audits/SILKSCREEN_LABELS.md).

## Install

Version 0.2.0 uses KiCad 10's native ActionPlugin runtime. It does not require the IPC API or a sibling plugin. Install the independent candidate PCM ZIP through **KiCad Manager → Plugin and Content Manager → Install from File**, restart PCB Editor, then use the plugin menu or toolbar icon.

For a source build, run `python build_pcm.py --output-dir candidate` from the WayriCAD root. The installer is `candidate/WayriCAD-silkscreen-label-0.2.0-PCM.zip`. Existing suite release 3.6.17 predates this plugin; a source catalogue entry does not make it part of that earlier release.

## Checks and limits

- Native text envelopes, font/justification and stroke geometry are checked conservatively against same-side text/graphics, body envelopes, pads/mask expansions, mask graphics, exposed tracks, vias/holes and a closed native board outline including cutouts.
- Dense placement searches a bounded field of nearby positions and tries readable horizontal/vertical orientations, placing the most difficult labels first. It is a safe local placement attempt, not a globally optimal annotation layout. Crowded layouts can remain unresolved. Checked guide paths may use an orthogonal bend; blocked paths remain unresolved.
- Rectangular envelopes can reject a placement that would fit between actual glyph strokes. The viewport uses simplified component/pad geometry; it does not establish physical accuracy or assembly access.
- Planning is read-only. Board, text, settings and geometry changes require a fresh preview. Apply failures restore edited labels and plugin-owned guides; rollback failures must be inspected before retrying.
- Windows native KiCad 10 is the tested target. Linux/macOS GUI and KiCad 11 behavior are not established. Native silkscreen DRC is still required; fonts, fabrication tolerances and assembly legibility need board-specific review.
- This window owns its operation history. Closing it discards that history; save only after review. Do not assume the PCB Editor's ordinary Undo has captured these native Python changes.

KiCad documents [silkscreen setup and design rules](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html). The plugin follows the board's native silk minimums; it does not replace fabricator requirements.
