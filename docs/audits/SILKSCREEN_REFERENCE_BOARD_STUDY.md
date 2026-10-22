# Silkscreen reference-board study

Measured on Windows with KiCad 10.0.6 on 22 October 2026. This study informs
placement priorities; it does not certify the reference boards or their
manufacturing clearances.

## Sources

| Board | Immutable source | SHA-256 of downloaded/original board |
|---|---|---|
| Berkeley Lab Marble | [Marble.kicad_pcb](https://github.com/BerkeleyLab/Marble/blob/a426777d92c0f22a546d4740b419a3937e0c1f90/design/Marble.kicad_pcb) | `3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512` |
| Henrik Forsten VNA | [vna.kicad_pcb](https://github.com/Ttl/vna/blob/7f11b07c3a7564caea9cf0405364d3bf34aaeb96/hardware/vna.kicad_pcb) | `f0955e397a7c2dd6be2d906ba1185b56c1a439e4f71261bd313467e6d573e9e5` |
| Henrik Forsten FMCW3 | [fmcw3.kicad_pcb](https://github.com/Ttl/fmcw3/blob/e57ce3bd46c862798b6acc4206564233bcbd5aaf/hardware/fmcw3.kicad_pcb) | `6dabb1611cb1ba9335e941e467e622a8b76591b6ddd3c55134f51517c3b69aa6` |
| White Rabbit Switch v3 SCB | [Altium PCB source](https://gitlab.com/ohwr/project/wr-switch-hw/-/blob/54f8a604978bdc65bbde5b1f4c7ec9bee3505a44/circuit_board/wrs_v3/SCB_SAM9G45/uTCA_MCH_PCB3.pcbdoc) | `f74bcabd7d073327e4236173cea4d2490bf661333d93c88d9bc052d482e82673` |

Marble's local file was also matched to its public Git blob
`b86e156a5cdfde48900bbed9ec88d8967e637d44`. White Rabbit was imported with
KiCad's native Altium importer into a disposable board. Import results are
separate evidence from the original Altium rendering and may differ.
No original board was saved or edited.

## What the boards actually contain

Counts include visible footprint **reference fields on F.SilkS or B.SilkS**.
Hidden references, references on fabrication layers, values and manually entered
text are excluded. Angles are reduced modulo 180 degrees.

| Board | Footprints | Visible silk references | Common text height | References at 0° or 90° |
|---|---:|---:|---|---:|
| Marble | 1,006 | 189 | 158 at 1.0 mm | 189 / 189 |
| VNA | 342 | 319 | 280 at 0.5 mm | 313 / 319 |
| FMCW3 | 429 | 417 | 409 at 0.6 mm | 413 / 417 |
| White Rabbit, native import | 774 | 767 | 761 at 0.5 mm | 765 / 767 |

Marble hides 817 references. VNA hides 23 and FMCW3 hides 12. The White Rabbit
import has one hidden reference and six visible references with no rendered
glyph geometry. A tidy board does not imply that every footprint has a visible
reference.

The measured smaller text sizes are observations, **not recommended fabrication
limits**. The placer must retain the board's manufacturing minimum and the
user's chosen minimum. A 0.5 mm reference in an older design is not permission
to shrink a different board below its minimum.

## Proximity

Distance is the shortest gap between the native rendered reference envelope and
the envelope of its own native courtyard. Zero includes contact or overlap.
Courtyard-free footprints are excluded rather than assigned invented courtyards.
Both board faces are measured independently.

| Board | References with native courtyard | Median gap | Within 1 mm | Within 2 mm |
|---|---:|---:|---:|---:|
| Marble | 161 | 0.250 mm | 144 / 161 | 157 / 161 |
| VNA | 285 | 0.189 mm | 276 / 285 | 284 / 285 |
| FMCW3 | 378 | 0.362 mm | 369 / 378 | 377 / 378 |
| White Rabbit, native import | 0 | Not measurable | Not measurable | Not measurable |

The White Rabbit importer supplies no native courtyards for this board. Its
height/orientation measurements are usable; claiming courtyard-clear placement
from that import would be unsupported.

## Placement lessons

Native top-side SVG exports were generated from each public board, showing
silkscreen, solder-mask openings and board outline, then rasterized for visual
inspection. The VNA and FMCW3 exports show compact local rows and columns,
interleaved labels between small parts, and frequent 90° labels in narrow gaps.
The White Rabbit import shows similarly compact reference banks. These layouts
support the following priorities:

1. Keep the label adjacent to its own footprint and preserve a clear visual
   association. Try nearby row/column positions and stagger neighbouring labels.
2. Use a common reading direction first. If a nearby horizontal label cannot
   fit, try an orthogonal label before unusual angles or distant placement.
3. Try the permitted smaller text sizes locally before searching farther away.
   Respect manufacturing minima throughout.
4. Use a direct, short association line when a leader is necessary. A line
   weaving around several components is a poor substitute for a nearby label.
5. Where local placement fails, try the nearest safe alternative with a visible
   connection to the correct component. Report unresolved labels explicitly.
6. Keep manual text and intentionally hidden or fabrication-layer references
   separate from automatic reference correction.

The reference boards are examples of human layout choices, not collision-free
training targets. Rendered reference envelopes intersect their own native
courtyards in 27 Marble, 61 VNA and 19 FMCW3 samples. This is a conservative
**envelope intersection**, not proof that every glyph stroke intersects a body.
Similarly, the single shortest envelope-to-courtyard line can cross a neighbour
while another direct visible line remains possible. These measurements must not
be used to relax the placer's outside-courtyard, pad, board-edge or silk
clearance checks.

## Reproduction and limits

The read-only measurement uses KiCad's `LoadBoard`, `BuildCourtyardCaches`,
`GetCourtyard`, and `TransformTextToPolySet` at 0.001 mm polygon error. It records
source SHA-256 before and after loading. Shapely computes envelope distances and
intersections from the exported native polygons. Height and orientation come
from the actual saved reference field. Legacy VNA/FMCW3 zone-fill conversion
warnings are suppressed only for read-only loading; the source bytes are
unchanged.

SVGs use `kicad-cli pcb export svg` with `F.Silkscreen,F.Mask,Edge.Cuts`,
`--mode-single`, `--fit-page-to-board`, and `--exclude-drawing-sheet`.
No solder-mask subtraction is applied, so the inspection shows the saved raw
silkscreen rather than concealing overlaps during plotting. Rasterization changes
presentation only. Source boards, generated renders and per-item measurements
remain validation artifacts and are not shipped in plugin packages.

A local comparison board was also inspected from a separate copy. Public access
to its repository could not be established, so no design data or measurements
from that board are included here.

No native DRC closure, fabrication qualification, or live-editor transaction is
claimed by this study. Any preview of the updated placer needs its own accepted
geometry, source-preservation and undo checks.
