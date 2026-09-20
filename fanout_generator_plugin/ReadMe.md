# WayriCAD Fanout Generator

<img src="icon.png" width="32" height="32" alt="WayriCAD Fanout Generator icon">

A fully local routing tool for PCB Editor. No hosted UI or remote preview assets are required.

![Current native fanout preview with via-in-pad and two escape angles](help-workflow.png)

Actual 3.1.1 window on a disposable SOIC fixture: pads 2–3 use via-in-pad, corner pads use 45° escapes, and pads 6–7 use 30° escapes. Existing copper is muted; new copper is teal. These example dimensions are not manufacturing recommendations.

## Fine-pitch perimeter packages

**Perimeter pitch expansion** is the default for SOIC, QFP and aligned perimeter-pad packages. Tracks launch straight beyond the pad ends, use staggered 45° bends, then finish parallel at a wider pitch. Outer tracks bend first; inner tracks remain straight longer, avoiding a compressed diagonal bundle.

![Actual QFP pitch-expansion preview](help-perimeter.png)

This disposable 32-pin fixture expands 0.5 mm pad pitch to 0.8 mm outer pitch. All 32 escapes were accepted; native DRC found no clearance or unconnected-item violations. Its 32 dangling-via warnings are expected because this fixture stops at escape vias rather than complete routed connections.

Under **Dimensions and advanced settings**, set **Straight launch** and **Outer pitch**. Zero outer pitch automatically accommodates the existing pad pitch and configured track/via clearance. Escape length is the minimum outward reach; the planner extends it when needed to fit the expansion and final straight section. An explicit pitch must not compress the pin bank. Direction/endpoint overrides are rejected for this style so the bends stay package-aligned.

Choose a BGA/grid style for array pads; center exposed pads need a separate via-in-pad group. Independent perimeter escapes do not promise differential coupling, length matching or impedance. Other-net obstacles and neighboring groups still undergo clearance checks. Non-perimeter and custom-angle styles remain explicit alternatives.

## Workflow

1. Configure geometry and pad scope or target net.
2. Click **Preview**. The canvas and result table show accepted candidates and rejection reasons. Preview creates no PCB copper.
3. Inspect the result, then **Apply to board**. A named WayriCAD group contains the committed geometry. Run KiCad DRC before saving or manufacturing.

The optional **More → Review placement again** command rechecks the board snapshot and prepares the same geometry; it is not required before Apply. **More → Clear preview** discards unattached candidates. Settings changes invalidate the preview. Board changes require a new preview. Plugin Undo/Redo preserves a recoverable group; reopen the tool to find its existing named groups.

## Controls and checks

Choose selected SMD pads, selected footprints, reference wildcards, or all SMD pads. Through-hole pads and pads without a net are excluded. Choose **Output → Via-in-pad** to place vias directly in selected pads, or **Escape traces** with radial, eight-direction dogbone, diagonal quadrant, perimeter, corner, or BGA/LGA diagonal style. Configure track width, escape length, angle, X/Y offsets, via diameter/drill, and copper clearance. **Netclass** filters pads using live board classes plus saved project explicit assignments and wildcard patterns. **Trace layer** lists actual enabled copper layers. Choosing a different layer creates a source via at the pad, then routes on that layer; this keeps the trace connected. Through vias span F.Cu to B.Cu.

The planner checks existing other-net pad/track envelopes, zones and routing keepouts, board edges/cutouts, and collisions between generated copper. Checks are conservative, so valid arrangements can be rejected. This is a fanout seed generator; it does not autoroute an entire BGA or guarantee manufacturing clearance.

## Advanced styles and high-speed selection

Choose **45-degree spread**, **Custom-angle spread**, **Straight + angled escape** or **Staggered rows**. The primary angle field supports footprint-aware spread, a board-absolute heading, or a footprint-relative heading. Advanced controls expose straight-launch length, stagger distance, net-name wildcards, pair gap, breakout skew and saved netclass dimensions.

Signal families include **DDR, GDDR, SERDES, PCIe, PCI, PXI, PXIe and LVDS**. Choosing a family leaves manual settings intact; **Load defaults** explicitly loads its suggested geometry and naming filter. Inspect the matched nets before applying. DDR/GDDR bus signals use independent escapes; narrow the filter to a clock/strobe pair before selecting paired mode. Profiles contain no assumed impedance or stackup-derived width.

**Auto differential pairs** reviews named mates together, routes a shared parallel section, reports actual escape lengths and rejects both members when a path, spacing or skew check fails. Every path segment appears in the canvas and exported SVG. See the bundled [advanced guide](advanced-fanout.md), [high-speed settings example](high-speed-settings.json) and [custom-angle example](custom-angle-settings.json). Example dimensions are illustrative and must be adapted to your board constraints.

![Paired escape preview](help-paired.png)

## Local preview

Primary choices remain visible; detailed dimensions and rejection tables are collapsed until needed. The clean, neutral canvas shows footprint outlines and references, real native pad polygons/rotation, existing copper, and generated geometry. A visible legend, millimetre scale, and coordinate orientation support review; the grid is optional and off by default. The resizable canvas supports wheel zoom at the cursor, drag to pan, double-click to fit, and via picking for coordinates. Pads, existing tracks/vias, zone outlines, and board edges provide context. Candidate copper and drill sizes use board units. Arc tracks currently appear as conservative bounding envelopes; native pads use their effective polygons; the IPC fallback uses supported padstack shapes. The canvas is a review aid, not a replacement for PCB Editor or DRC.

## Command line

Use KiCad 10's bundled Python so `pcbnew` is available. List JSON option names and actual project choices with `python -m wayricad_runtime.cli fanout settings --board source.kicad_pcb` (or `stitching settings`). Settings are a JSON object, for example:

```json
{"scope":"Reference wildcard","ref":"U1","pattern":"Dogbone outward","length":1.2,"width":0.2,"via_diameter":0.6,"via_drill":0.3,"clearance":0.2}
```

```text
python -m wayricad_runtime.cli fanout plan --board source.kicad_pcb --settings settings.json --output plan.json --svg preview.svg
python -m wayricad_runtime.cli fanout apply --board source.kicad_pcb --plan plan.json --output routed.kicad_pcb
```

Plan is read-only and produces reviewable JSON plus an optional standalone local SVG. Apply recomputes and checks the reviewed geometry and board fingerprint, then writes a **new** `.kicad_pcb` file. It refuses source overwrites, existing destinations, empty plans, and stale or altered candidate geometry. The source remains unchanged.

## Compatibility

Native in-memory board tests, file round-trips, and hidden wx frame smoke checks run against KiCad 10. The suite also packages an IPC entry point for forward compatibility; supported geometry depends on the live IPC API. Unsupported capabilities fail explicitly. Live KiCad 11 behavior must be validated against its released runtime.

Use **Per-pin / net groups** to combine different styles, layers, dimensions and
via-in-pad rules in one reviewed plan. Rules match net names, netclass, references
and pad numbers in order; unmatched pads can use defaults, be skipped, or stop the
preview. See [group workflow and JSON example](advanced-fanout.md#different-styles-for-different-pins-and-nets).


## Different rules for different pins

Expand **Per-pin / net groups** and open the rule list. Add a named rule, match its nets/netclass/references/pads, then override only the geometry you need. Put specific rules above broad rules: the first match wins. Preview again after changing rules and inspect the **Group** column under candidate details.

![Ordered fanout groups](help-groups.png)

The example separates via-in-pad and two escape angles. Each group can also select a different enabled copper layer. Group names describe user intent; the selectors determine which pads actually match.


## Adaptive escapes around existing routing

![Adaptive preview continuing an existing stub while avoiding nearby copper](help-adaptive.png)

Four selected signals on a disposable SOIC fixture. Muted copper already exists; teal is the proposed addition. The right-hand upper escape continues the existing two-segment stub.

Set **Routing → Adaptive**, choose a narrow pad/net scope and preview. This is a separate option from the fanout style. It searches nearby simple paths with up to two 45° bends, ranks shorter added copper before extra bends, and checks existing/generated copper and the board edge. Perimeter pads retain a straight outward launch before the search expands; BGA/grid styles can search all directions.

A simple existing straight-track stub is continued from its open endpoint. Existing tracks are never moved, removed or rewritten. Already connected pads, branches, loops, arcs, existing via endpoints and same-net zone topology are reported for manual review rather than guessed. **Via-in-pad** remains a fixed placement; coupled differential pairs use Fixed routing.

**Adaptive radius** limits endpoint distance from the pad or continued stub, and **Adaptive search step** sets the candidate lattice. Defaults are 3 mm and 0.25 mm. Search is limited to 4,096 checked candidates and three seconds per pad, with a maximum 20 mm radius and radius/step ratio of 20. This is the shortest valid result in the examined candidate family, not proof of a globally optimal route. Narrow the scope when reviewing dense designs. Failed searches retain an explicit rejection reason.

CLI settings use `"routing_mode":"Adaptive"`, `"adaptive_radius":3`, `"adaptive_step":0.25`; they also work as per-group overrides. Preview/apply uses the same search and stale-board checks.
