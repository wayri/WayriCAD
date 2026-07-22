# KiWay Via Stitching

Generates a reviewed grid of same-net stitching vias inside full-board or
selection-derived bounds while excluding unrelated board geometry.

## Capabilities

- Select a real PCB net and automatically follow selected pads/tracks/zones.
- Full-board or live PCB-selection bounds with spacing and edge inset controls.
- Optional restriction to the target net's filled copper zone.
- Exclusions for footprint bodies, named references, unrelated tracks/vias,
  unrelated zones, keepouts, and drawings.
- KiCad-style window preview, temporary PCB preview, rejection counts, and gated
  commit.
- Persistent named PCB groups for undo after reopening the plugin.

## Limitations

Candidate checks are geometric prefilters, not DRC. Filled-zone hit testing
depends on the current zone fill; refill zones before previewing. The generator
does not calculate return-current benefit, resonant spacing, thermal behavior,
fabrication aspect ratio, or high-frequency fence spacing. Run DRC and inspect
every committed pattern.
