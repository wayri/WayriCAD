# WayriCAD Fanout Generator

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD Fanout Generator icon">

## Live preview and faster planning

### Choose → Style → Review

1. Select footprints or pads, or enter a reference wildcard. Expand **Limit pins
   or nets** to restrict pin numbers and net names with comma-separated wildcards.
2. Choose a style. The small component preview shows its actual accepted routes.
   Dimensions and routing options remain under advanced settings.
3. Review the accepted/rejected counts and **Before / After** comparison, then
   apply separately. **Cancel** stops an isolated preview; changing inputs
   immediately disables Apply and discards outdated results.

**Saved board · fast** plans in a separate native process from a private copy,
leaving the window responsive during planning. Save editor changes first.
**Live snapshot · slower** captures unsaved geometry explicitly; native capture
can pause the window and therefore requires manual Refresh rather than automatic
style refresh. Unsaved project rules must match the snapshot's effective
netclass dimensions; mismatches are rejected. IPC previews use a fresh connection
to the originating editor; uninspectable live netclass dimensions require explicit
reviewed dimensions. Neither path bypasses Apply's source/rule checks or native DRC.

Select parts or pins in PCB Editor, then choose a **Fanout style**. **Live
preview** is on by default: selection changes and edits update the candidates
after a short pause. **Selected style on component** shows the actual accepted
fanouts in a small preview; use its component list when several parts are
selected. The main canvas keeps the complete plan. A blocked component still
shows its pads with zero accepted escapes; rejection details remain available.

![Live fanout style preview on a selected QFP](help-live-preview.png)

Actual native window on a disposable 32-pin QFP fixture: all 32 perimeter
escapes accepted. Dimensions are illustrative. Existing screenshots below are
retained. This is a source-window check, not installed-editor qualification.

| Action | Behaviour |
|---|---|
| Change selection or style | Immediately disables Apply, then refreshes after 300 ms without further edits. PCB selection is checked every 500 ms. |
| Inspect another selected part | Choose it in the small preview's component list; no board copper changes. |
| Work on the whole board | Choose the broad scope and click **Refresh preview**. Unrestricted reference wildcards also need explicit refresh. |
| Turn off Live preview | Edit freely, then use **Refresh preview** when ready. |
| Apply | Remains a separate action, with source/rule/settings checks and recoverable groups. |

Detailed dimensions, signal-family defaults and netclass filters are under
**Dimensions and advanced settings**. Connector exit controls appear for the
connector style. Both preview panes support pan/zoom; hovering and dragging use
cached pixels, followed by an exact redraw after a drag. Settings changes reuse
display context only for the same snapshot mode, source path and saved file stamp;
Apply always performs fresh geometry and rule checks.

Earlier 3.6.27 measurement: fresh fixed-style planning on Marble U35 fell from **21.94 s to 0.29 s**, with
identical full plans and rejection reasons. The complete new native preview
pipeline took 3.54 s initially and 2.86 s on refresh; source checks remain a
significant cost. See the [benchmark and limits](../docs/audits/FANOUT_LIVE_PERFORMANCE_2026-10-23.md).
That earlier measurement predates the richer source guards and isolated source workflow.

Current source validation on public Marble U35 produced the same 103 accepted
escapes and 258 rejections. Preview submission took 22–55 ms and the largest
20 ms timer gap was 323–376 ms. Full completion was 13.72 s initially and
9.17–10.11 s on refresh, versus 8.24–9.14 s for the old synchronous UI call.
Isolation improves responsiveness and adds startup overhead; it is not an
end-to-end solver speedup. These changes are included in release 3.6.28.
An additional instrumented capture completed in 13.08 s with a 0.695 s largest
timer gap. See the [current suite validation](../docs/audits/SUITE_RESPONSIVENESS_2026-10-23.md)
for source checks and remaining limits.

![Guided native preview on public Marble U35](help-guided-preview.png)

Actual Windows / KiCad 10.0.6 source window using the public Marble board;
103 accepted escapes, 258 rejected. No source board was modified or private
path displayed. This does not qualify an installed or connected-editor workflow.

## Capabilities

- Generate perimeter pitch expansion, BGA/grid dogbones, 45-degree/custom-angle spreads, staggered escapes and via-in-pad placements.
- Assign different styles, dimensions and copper layers by ordered pad, reference, net or netclass groups.
- Use optional adaptive routing to avoid existing copper or continue a supported simple open stub.
- Review named differential-pair escapes, shared parallel sections, escape lengths and configured gap/skew checks.
- Preview actual board context and rejection reasons before applying recoverable groups; use CLI plan/apply with JSON and SVG.

## Limitations

- This generates fanout seeds, not complete autorouting or guaranteed impedance, timing or protocol compliance.
- Adaptive routing searches a bounded candidate family; branches, loops, arcs, existing-via endpoints and same-net zone topology require manual review. Coupled pairs use fixed routing.
- Via-in-pad needs fabricator review; through vias span F.Cu to B.Cu. Plated through-hole pins are supported by Connector edge; other styles exclude them. Non-plated holes and pads without nets are excluded.
- Conservative obstacle checks can reject feasible layouts; native KiCad DRC remains required. KiCad 11 live behavior is unverified.

## Overview

A fully local routing tool for PCB Editor. No hosted UI or remote preview assets are required.

![Current native fanout preview with via-in-pad and two escape angles](help-workflow.png)

Actual 3.1.1 window on a disposable SOIC fixture: pads 2–3 use via-in-pad, corner pads use 45° escapes, and pads 6–7 use 30° escapes. Existing copper is muted; new copper is teal. These example dimensions are not manufacturing recommendations.

## Connector-edge breakout

1. Select a connector footprint or individual pins in PCB Editor. Choose **Selected footprints** or **Selected pads**. For every connector on the board choose **All connector pads** and narrow the pin/net filters as needed. Alternatively choose **Reference wildcard** and enter the connector reference under advanced settings.
2. Choose **Connector edge**. This enables plated through-hole and SMD pins, independent pin routing and a bounded obstacle search. Endpoint vias default off for this style.
3. Select **Nearest edge**, **Top**, **Bottom**, **Left** or **Right** in footprint-local coordinates. Set **Beyond connector body** (initially 0.5 mm) and the trace layer. The target uses the courtyard when available, otherwise the body/pad hull. PTH pins already span copper layers, so routing on B.Cu does not add an unnecessary source via.
4. Under advanced settings, filter **Pin numbers** and **Net names** with comma-separated wildcards, for example `1,2,5` and `/Interface/*`. Both filters combine with PCB selection and netclass. Use per-pin/net groups for different layers or dimensions.
5. Click **Preview**. Inspect routes and rejected pins, then **Apply to board**. Existing copper is retained. Connected pins are rejected rather than given duplicate escapes; non-plated mounting holes, other copper, zones and board edges remain obstacles. Run native KiCad DRC.

![Native connector-edge preview](help-connector.png)

Actual KiCad 10 wxPython window on a disposable six-pin plated connector fixture. All six independent escapes were accepted. This is an illustrative fixture, not validation of a particular connector or manufacturing process. No personal paths appear in the capture.

**Local clearance:** leave the field blank to preserve normal clearance. For a reviewed local exception, enter the requested clearance (at least the board fabrication minimum), preview, and use **Export local-rule review…**. Choose a new project name: a new directory of that name contains the board, project and scoped custom rules. Live Apply is disabled for these candidates. The source stays unchanged. The rule covers only enclosed copper pairs on the chosen layer, with at least one selected net, inside a named connector rule area. Hole and board-edge constraints remain unchanged; existing custom rules retain higher priority. Open the exported project and run DRC before adopting it.

The search is bounded to 4,096 visited grid positions and three seconds per pin. It may reject dense or blocked connectors; narrow the scope, change the exit side/layer, or use a finer **Adaptive search step**. Differential-pair/skew constraints require the existing paired styles; Connector edge does not certify protocol performance.

CLI settings use `pattern: "Connector edge"`, `pad_filter`, `net_filter`, `connector_exit`, `connector_edge_margin` and optional `connector_clearance` (millimetres; blank keeps normal clearance). Use the existing `fanout plan` / `fanout apply` commands. With local clearance, apply creates a new review directory named after the output board stem, containing all three project files. A changed board or saved custom-rule/netclass input invalidates the plan.

Local rules use KiCad's [enclosedByArea condition](https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html#custom_design_rules): the whole item must be inside the area, not just its center.

## Fine-pitch perimeter packages

**Perimeter pitch expansion** is the default for SOIC, QFP and aligned perimeter-pad packages. Tracks launch straight beyond the pad ends, use staggered 45° bends, then finish parallel at a wider pitch. Outer tracks bend first; inner tracks remain straight longer, avoiding a compressed diagonal bundle.

![Actual QFP pitch-expansion preview](help-perimeter.png)

This disposable 32-pin fixture expands 0.5 mm pad pitch to 0.8 mm outer pitch. All 32 escapes were accepted; native DRC found no clearance or unconnected-item violations. Its 32 dangling-via warnings are expected because this fixture stops at escape vias rather than complete routed connections.

Under **Dimensions and advanced settings**, set **Straight launch** and **Outer pitch**. Zero outer pitch automatically accommodates the existing pad pitch and configured track/via clearance. Escape length is the minimum outward reach; the planner extends it when needed to fit the expansion and final straight section. An explicit pitch must not compress the pin bank. Direction/endpoint overrides are rejected for this style so the bends stay package-aligned.

Choose a BGA/grid style for array pads; center exposed pads need a separate via-in-pad group. Independent perimeter escapes do not promise differential coupling, length matching or impedance. Other-net obstacles and neighboring groups still undergo clearance checks. Non-perimeter and custom-angle styles remain explicit alternatives.

## Workflow

1. Select parts or pads and choose a style. The live preview follows selected components.
2. Inspect the main canvas and small component preview; expand candidate details for rejection reasons. Use **Refresh preview** for broad scopes or after board geometry edits. Preview creates no PCB copper.
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


## Resize the workspace and find help

Drag the settings/board-preview divider to inspect source pads, escape controls or connector-edge settings at a readable width. Expanded settings scroll inside their own pane; preview and Apply remain separate actions.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.
