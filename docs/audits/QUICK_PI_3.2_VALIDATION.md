# Quick PI 3.2: native Marble power-rail validation

**PASS for the exercised Windows native workflow:** actual worker inspection and
solve, Net/Mesh/Results rendering, all seven result metrics, and local HTML export.
The board file remained byte-for-byte unchanged. This is an operational and
numerical screening check, not full-board PI signoff.

## Board and deliberately selected rail

- Local Berkeley Lab Marble fixture, identified by its board hash below; an independent upstream revision was not recorded for this copied fixture.
- Board SHA-256: `3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512`.
- Net: **MGTAVCC**, selected because it is an actual FPGA supply rail containing
  filled zones, traces and vias; this replaces a random small-net choice for
  this particular validation.
- Source: **L34.2**, the rail-side pad of the Murata BLM18SG121TN1D ferrite bead.
- Sink: **U1.C6**, a supply ball of the XC7K160T FPGA.
- The saved board has MGTAVCC zones on **In7.Cu (56.70 mm²)** and
  **B.Cu (50.76 mm²)**. These are native zone filled areas, not total merged
  conductor areas; the merged In7 layer includes approximately 57.47 mm².

Explicit test excitation was **1 V at L34.2 and a hypothetical 1 A sink at U1.C6**.
It concentrates the load at one ball to make the test reproducible. It does not
claim the FPGA normally draws 1 A through that ball, or reproduce its distributed
multi-pin load. The model includes copper on this rail; it excludes ferrite
component loss, upstream regulator behavior and ground-return loss.

The extracted geometry included **49 tracks, 14 pads, 2 filled zones, 12 vias and
1 plated pad**. Saved stackup information supplied layer Z positions and 35 µm
copper thickness. Via plating was explicitly 25 µm. Curve approximation tolerance
was 0.005 mm, with no gap snapping. The solver reported no floating triangles.

## Mesh refinement results

These results were rerun after the final 3.2 mesher update; the triangle counts,
values and screenshot below replace the earlier mesher run.

| Requested edge | Triangles | Drop at 1 A | Copper loss | Peak sheet J |
|---|---:|---:|---:|---:|
| 0.5 mm | 13,382 | 2.519869 mV | 2.519869 mW | 81.5652 A/mm² |
| 0.25 mm | 21,491 | 2.597100 mV | 2.597100 mW | 85.9836 A/mm² |
| 0.125 mm | 64,383 | 2.641906 mV | 2.641906 mW | 90.9052 A/mm² |
| 0.0625 mm | 292,974 | 2.657125 mV | 2.657125 mW | 100.1537 A/mm² |

Successive drop changes were **2.974%, 1.696% and 0.573%**, relative to the finer result. Copper-sheet loss changes were **5.839%, 3.274% and 1.098%**. The automated two-step 1% study correctly reports **NOT_STABLE**. Refinement to 0.03125 mm was refused by the mesh budget; no result is invented for that level. Peak sheet current rises on each mesh and is **not converged**. Do not derive a fuse rating or safe current from these peaks.

The finest mesh had 156,815 nodes; current balance error was 5.28e-11 A and relative energy error 1.19e-11. These algebraic checks pass but do not establish discretization accuracy. See [reference benchmarks and criteria](../PI_REFERENCE_BENCHMARKS.md).

On the 0.5 mm mesh, losses were **1.238179 mW in sheets + 1.281690 mW in via
connections**, with an approximately `1.3e-18 W` accounting difference. The
current-balance error was `8.33e-11 A`, maximum nodal residual `2.65e-11 A`, and
relative energy error `2.13e-11`. Those small algebraic errors do not erase
geometric/material or mesh-discretization uncertainty.

Thus this particular zoned rail and terminal pair gave about **2.5–2.7 mV at
1 A**, not 35 mV. That does not establish a universal drop for Marble's other
rails, different terminal pairs or distributed loads.

## Native display and report checks

The native window executed the real inspection/solver worker and displayed:

- Net geometry and Mesh pages;
- potential, voltage drop, DC transfer resistance, current density, current
  flow, copper loss density and adiabatic pulse-risk views;
- layer-specific copper thickness, area and loss;
- a self-contained local HTML report.

All render calls completed with no caught native/main-loop rendering exception.
The worker/window/report sequence took about 23 seconds on this machine; this is
an observed smoke duration, not a portable performance guarantee. KiCad's duplicate
image-handler warnings were emitted during imports, without stopping operation.

![Actual Quick PI MGTAVCC result, intentionally zoomed to the In7 copper plane](../../quick_pi_plugin/help-power-rail.png)

The screenshot shows the **0.5 mm** result and is intentionally zoomed into the
In7 plane. Its displayed color scale describes that layer; the terminal-to-terminal
drop includes the other copper layers and via connections. Full-net Fit also
includes distant same-net pads/drilled contacts, which can make the plane small;
pan/zoom was exercised to inspect it. Existing small-net help screenshots remain
separate to avoid changing their captions or implied test case.

## Evidence and limits

Local evidence scripts/results are under `.validation/quick-pi-3.2/`:
`rail_solve.py`, `refine.py`, `fine.py`, `native_ui.py`, request/bundle JSON files,
`native-ui-validation.json`, and `MGTAVCC-rail.html`. The validation record includes
the before/after board hash and per-view render checks. These local large result
files are not release fixtures.

This check does not validate AC impedance, transient decoupling response,
temperature feedback, package contact physics, fuse opening, or full 3D current
distribution. Pulse risk is the stated adiabatic screening model. Linux/macOS GUI
behavior and multiple-editor origin selection require their separate suite checks.
