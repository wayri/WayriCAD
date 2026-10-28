# Published inset-fed patch benchmark

Open `published_patch.kicad_pro` in KiCad 10. This is a reusable saved-copper
reconstruction of the **conventional, unslotted, unloaded Figure 1(a)** in
Junho Yeo and Jong-Ig Lee, *Slot-Loaded Microstrip Patch Sensor Antenna for
High-Sensitivity Permittivity Characterization*, Electronics **8** (2019), 502,
[doi:10.3390/electronics8050502](https://doi.org/10.3390/electronics8050502).
The paper is CC BY 4.0; this reconstruction by WayriCAD contributors adapts its
dimensions into native KiCad geometry. The paper PDF is not bundled.

| Parameter | Value |
| --- | --- |
| Board and full B.Cu ground | 80 × 80 mm |
| RF-35 dielectric | εr = 3.5; tanδ = 0.0018; thickness 0.76 mm |
| F.Cu rectangular patch | 40 × 31.9 mm |
| Feed width; external length | 1.66 mm; 24.5 mm |
| Inset depth; clearance on each side | 9 mm; 2.8 mm |
| Reference impedance | 50 Ω |

Section 2 (page 4) gives these dimensions; Figure 1(a) (page 3) shows that the
2.8 mm inset width is **one side clearance**, and the 24.5 mm feed length is
outside the patch. Total notch width is therefore 7.26 mm.

KiCad uses downward Y: the board spans (0, 0)–(80, 80), the patch spans
X = 20–60 and Y = 23.6–55.5 mm, and the feed reaches Y = 80 mm. In a centered
solver coordinate system with upward Y, the patch center offset is +0.45 mm.
`SIGNAL` is the single connected F.Cu patch/feed polygon; `GND` is the full
B.Cu plane. There are no components, vias, soldermask coatings or superstrates.

The explicit stackup keeps **0.76 mm dielectric separation**. Each copper foil
is drawn as 0.035 mm only as an assumption, giving 0.83 mm total drawing
thickness. The paper does not specify conductor thickness or conductivity.
The FEM PEC-sheet model ignores these assumed foil thicknesses and copper loss;
it must not use the total board thickness as dielectric separation.

In Quick EMerge choose Saved PCB rule-area region, load the named full-board
rule area, and select F.Cu `SIGNAL` and B.Cu `GND`. Native extraction and planning
produce one ideal 1.66 mm boundary port at the feed end, with no geometry
blockers. Review εr and loss tangent explicitly in the workbench. The matching
patch-template setup can also be used for comparing the two geometry paths.

The published unloaded CST resonance is 2.500 GHz (Table 3, page 13), compared
with measured 2.528 GHz (Table 4, page 14). The simulated conventional-patch
VSWR < 2 band is 2.490–2.510 GHz (page 5); that threshold equals −9.542 dB,
not −10 dB. The paper supplies no tabulated exact conventional S11 minimum.
Port details, copper loss and mesh convergence limit exact reproduction.

Copper is intentionally preserved to the board edge using native saved filled
polygons. Refilling with ordinary manufacturing edge clearances can change that
geometry; retain the supplied fill for this research comparison. This project
is a numerical benchmark, not a manufacturing release or schematic design.
Native reload checks independently confirmed outline and net/layer identity,
1266.27 mm² signal copper, 6400 mm² ground copper, bounding boxes and inset/feed
cross-sections. Native KiCad SVG export was visually checked.

A native DRC run without refill was stopped after exceeding the bounded
geometry-review budget; it produced no completed report. No DRC-clean or
manufacturing-readiness claim is made. The saved geometry remained unchanged.

See [recorded comparison](COMPARISON.md) for the completed saved-copper solves,
controlled refinement study and its acceptance limits. Numerical agreement is
not qualified. The supplied setups retain the earlier coarse workflow; they do
not reproduce the later controlled adaptive study.
