# Marble analysis fixes — candidate 3.6.11

## Source and execution

Windows, KiCad 10.0.6 native Python. The saved Marble PCB was loaded without
changing its bytes. Source SHA256:
`3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512`.
It contains 12 copper layers, 3,664 vias and 127 zones. Runs use the saved
physical stackup; fabrication stackup and measured hardware were not verified.

## Quick SI

Automatic saved-stackup screening now separates first-order travel time from
reference coverage and discontinuity extraction. Without manual Er/Z0 overrides:

| Endpoint path | Length mm | Delay ns | Disposition |
|---|---:|---:|---|
| MII_MDC U6.8 → U54.16 | 253.670353 | 1.789567 | Approximate |
| FMC2 clock P P2.B20 → C101.2 | 212.997868 | 1.469919 | Approximate |
| FMC2 clock N P2.B21 → C89.2 | 212.990659 | 1.471676 | Approximate |

Timing assumes ideal continuous adjacent reference planes and dielectric travel
through vias. It does not solve via reflections or differential coupling.
Reference blockers remain visible; supported section impedances and local
endpoint screening are shown separately from a uniform route Z0. A zone corridor
still needs a distributed field model. Three offline Matplotlib plots expose
section impedance, cumulative delay and cumulative DC resistance.

The independent PCM ZIP ran the actual clock-N analysis using native KiCad
bindings and reproduced the source result. This was a CLI workflow, not a live
PCB Editor interaction.

## QuickTherm and Quick PI reports

Thermal reports include saved Edge.Cuts, component bounds, drills and slots,
mirrored bottom view, an illustrative 3D extrusion, cursor probes and sortable
cross-selection. Three embedded Matplotlib plots show top, bottom and component
temperatures. The 3D view is not STEP geometry. Thin-sheet fields explicitly share
one midplane temperature across faces; multilayer fields retain separate layers.
Unknown case temperatures are not inferred from junction values.

Quick PI places voltage drop, current density and copper loss density plots
first; additional maps remain in an expandable section.

## Plated slots

The thermal model retains rotated obround drill dimensions and actual flashed
land polygons. Axial plating area uses the exact outward capsule-wall area
`A = t[2(a-b)+pi*b] + pi*t^2`, with major/minor dimensions a/b and plating t.
Conductance uses `k*A/L` in SI units. Distributed cell contacts remain an
approximation, not a resolved 3D barrel/land mesh. Coarse contact proxies are
counted explicitly. Missing geometric evidence is not converted into a pass.

The actual grid-24, 12-layer solve completed in 60.438 seconds with 8.3 W of
assumed input dissipation. Heat balance residual was -1.20e-11 W. Assumed power,
thermal resistance, plating and environment settings are scenario inputs, not
measured Marble operating conditions. The grid-48 production worker and report export completed in 196.094 seconds; heat residual was 7.28e-12 W. It retained all 3,852 plated barrels (3,664 vias plus 188 PTH pads), including seven slots. The maximum junction-temperature change between grids was 0.301 °C; this does not establish 0.1 °C mesh convergence. At grid 48, 165 coarse barrel-contact proxies remained explicitly flagged.

Repeated hole-ring scans were reduced with conservative bounding-box pruning.
Tests compare pruned predicates and clipped areas against their original exact
implementations. Slot rotation is checked against native KiCad drill polygons.

## Verification limits

Automated imports, native analysis runs, analytical checks and generated plot
inspection do not establish protocol compliance or hardware temperature accuracy.
Local browser file navigation was blocked by tool policy; interactive report
click behavior was not verified through that browser tool. Numerical completion
is distinct from mesh convergence and physical qualification.
