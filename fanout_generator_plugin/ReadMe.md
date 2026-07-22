# KiWay Fanout Generator

Generates reviewable escape-routing starters from selected SMD pads. It is
intended for BGA, LGA, QFN, and dense peripheral packages where repetitive
track/via placement is useful before manual routing.

## Capabilities

- Live PCB selection with scopes for selected pads, selected footprints,
  reference wildcards, or all SMD pads.
- Dogbone inward/outward, BGA/LGA grid, quadrant inward/outward, four-corner
  inward/outward, perimeter, radial, and via-in-pad patterns.
- Configurable track width, escape length, copper layer, via diameter, and drill.
- KiCad-style window preview, temporary selected PCB preview, and gated commit.
- Persistent named PCB commit groups, allowing Undo Last Commit after reopening.
- Double-click preview rows to select the corresponding PCB pad.

## Workflow

Select pads or a footprint in PCB Editor, choose the scope and escape pattern,
then inspect **Preview in Window**. Use **Show on PCB** for placement and DRC
inspection. Only **Commit to PCB** keeps the geometry. Run DRC and finish routes
manually before fabrication.

## Limitations

This is not an autorouter or package-specific escape optimizer. It does not
guarantee neck-down rules, via technology availability, escape-channel capacity,
return-path continuity, or manufacturability. Via-in-pad requires fabrication
support for filled/capped vias. KiCad 10 does not expose `BOARD_COMMIT` to Python;
the plugin therefore uses persistent named PCB groups for post-close bulk undo.
