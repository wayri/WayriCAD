# Advanced fanout and high-speed escapes

The local Fanout Generator supports angled and segmented escapes, net-name and netclass selection, and paired breakouts. These generate the first part of a route; dimensions and channel constraints still come from your board design.

## Styles and angles

| Style | Geometry |
| --- | --- |
| 45-degree spread | Fans pads away from the footprint at 45° to the nearest footprint edge normal. |
| Custom-angle spread | Uses the same spreading direction with an editable outward angle below 90°. |
| Straight + angled escape | Starts normal to the footprint edge, then turns to the selected spread angle. Escape length includes the straight launch before XY offsets. |
| Staggered rows | Alternates the escape length by the row-stagger distance in deterministic footprint/pad-position order. |

Existing dogbone, BGA/LGA, quadrant, perimeter, corner and radial styles remain available. Choose **Pattern** direction for footprint-aware spreading, **Board absolute** for a fixed heading, or **Footprint relative** for a heading that follows component rotation. In board coordinates, 0° points toward +X and 90° toward +Y (down the preview). The existing angle offset rotates the chosen heading. Absolute/relative headings accept 0–360°. Via-in-pad remains a separate output mode.

## Select the intended signals

Choose a signal family and explicitly load its defaults. Presets suggest geometry, naming filters and independent/paired behavior; they do not invent trace widths or impedance values. Review the net-name filter and netclass against your project. Comma-separated wildcards let you narrow a bus, byte lane, strobe or link. Explicit CLI settings override profile suggestions.

DDR/GDDR include single-ended data/address/control signals and differential clocks or strobes. Select a data group in **Independent** mode; select its clock/strobe pair in **Auto differential pairs** mode. Full memory-interface matching is group- and stackup-dependent. [TI DDR layout guidance](https://edgeworker.ti.com/lit/an/sprad06c/sprad06c.pdf).

SERDES, PCIe, PXIe and LVDS profiles suggest paired escapes. PCI and PXI remain independent bus presets; PCIe/PXIe are separate choices. [NI PXI architecture](https://www.ni.com/en/shop/pxi/overview-pxi.html).

Enable **Use selected netclass dimensions** to read track/differential width, gap, clearance and via dimensions from the selected saved project class. Missing class data produces an actionable error. Custom KiCad rules can further constrain these values; final KiCad DRC still applies.

## Differential-pair review

Pair mode requires exactly one positive and one negative pad per named pair within the filtered footprint. It recognizes P/N and +/− suffixes, plus delimited T/C clock/strobe names. Missing or ambiguous mates are rejected. Both members must share the selected layer and via transitions.

Paired escapes use a common heading, a converging launch and a parallel section separated by trace width plus edge-to-edge pair gap. Optional terminal vias flare apart to meet their clearance. In this mode, escape length controls forward reach; the table and JSON report the actual generated trace length. Pair geometry takes precedence over individual-pad styles.

Set a maximum breakout skew in millimetres. Both members are rejected together if either path is blocked or their generated lengths differ too much. All bends, vias, board edges and relevant-layer obstacles are checked. The tool does not add tuning serpentine, stitch return vias, calculate stackup impedance, compensate package delay, or certify a full interface. KiCad distinguishes differential gap, uncoupled length and skew constraints, while physical transitions also affect high-speed behavior. [KiCad differential routing](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#routing-differential-pairs), [TI high-speed layout guidance](https://www.ti.com/lit/an/spraar7j/spraar7j.pdf).

## CLI

```text
python -m wayricad_runtime.cli fanout settings --board source.kicad_pcb
python -m wayricad_runtime.cli fanout plan --board source.kicad_pcb --settings high-speed-settings.json --output plan.json --svg preview.svg
python -m wayricad_runtime.cli fanout apply --board source.kicad_pcb --plan plan.json --output escaped.kicad_pcb
```

Use KiCad 10's native Python for file commands. The JSON and local SVG contain every bend, measured length and pair identity. Apply rechecks the source board and all reviewed geometry, then writes a new output file. In the GUI, settings changes invalidate the preview; Preview → Apply and grouped Undo/Redo remain the workflow.
