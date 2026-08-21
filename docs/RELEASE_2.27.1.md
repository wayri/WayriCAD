# KiWay v2.27.1 Release Notes

## Heater Designer Preview Fix

PCB / Foil Heater Designer 0.1.2 fixes a blank preview window. The preview
panel relied on asynchronous repaint delivery that never arrived after the
initial layout pass, so Generate and Run Thermal Simulation appeared to do
nothing. The panel now:

- repaints synchronously whenever its size changes (the initial layout
  included),
- flushes the repaint immediately when a pattern or thermal result arrives,
- suppresses background erasure flicker, and
- skips degenerate sub-minimum sizes safely.

Verified by an instrumented render probe across Serpentine, Concentric
spiral, and Zoned raster patterns plus the thermal gradient view.

## Planar Magnetics Hardening

Planar Magnetics 0.2.2 applies the identical lifecycle hardening to the
winding preview and motion plot, which previously depended on tab switches
to force their repaints.

## Package Updates

Heater Designer 0.1.2, Planar Magnetics 0.2.2. Suite version 2.27.1.
