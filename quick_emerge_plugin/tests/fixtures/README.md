# Native PCB region fixtures

`region_coupon.kicad_pcb` is the original two-layer extraction coupon.

`antenna_region.kicad_pcb` is a synthetic antenna-on-board geometry fixture,
created with KiCad 10.0.6. It contains a 100 × 70 mm board, a 28 × 22 mm top
copper patch and 2 mm feed on SIGNAL, and a bottom GND plane. The non-enforcing
**Antenna region** rule area spans X=50–98 mm and Y=15–55 mm. The saved dielectric
separation is 1.53 mm; total board thickness is 1.6 mm. Its actual filled copper
produces one supported boundary feed port when extracted.

The fixture demonstrates selecting antenna copper from a larger board. It is
not a tuned antenna, populated assembly or measured/converged RF reference.
The cropped model omits the board outside the rule area. Native DRC reports a
free feed-track end and two isolated copper fills: there are deliberately no
component pads. The area does not prohibit copper or placement. These fixture
findings are recorded rather than presented as a manufacturing-clean design.
