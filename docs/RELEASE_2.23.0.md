# KiWay v2.23.0 Development Notes

This development release adds two independently installable KiCad 10 packages.

## Harness and Cable Workbench 0.2.0

- Ingestion of up to 50 board pin-export projects.
- Indexed multi-board matching and connector rules with pin-for-pin, offset,
  or explicit pin maps.
- Harness-only loads, bundles, splices, gauges, colors, shields, and lengths.
- Sortable wire, pin, net, and procurement BoM views.
- Native pan/zoom system draft and universal SVG export.

## PCB / Foil Heater Designer

- Serpentine, zoned-raster, and concentric-spiral copper synthesis.
- User-defined regional resistance factors for controlled hot and cold areas.
- Multilayer series paths and transition-via generation.
- Electrical loading, local Joule-loss, and temperature-coefficient reporting.
- Reduced-order steady-state 2D conduction/convection simulation with thermal
  map, peak, average, and uniformity results.
- Window preview, temporary PCB preview, guarded named-group commit, CSV and
  JSON export, and integrated safety/limitations help.

## Planar Magnetics & Actuator Workbench

- Rectangular and circular planar windings across up to 16 layers.
- Series layer transitions, via-stitched geometry, optional transformer
  secondary, coupling, and turns-ratio modeling.
- Built-in air, planar E, RM, pot, toroid, powder, ferrite, and
  nanocrystalline core examples plus JSON catalog import/export.
- DC/AC resistance, inductance, parasitic capacitance, self resonance, Q,
  copper/core loss, saturation, field, force, travel, and magnetic-torquer
  torque estimates.
- Voice-coil, linear-solenoid, PCB motor, and magnetic-torquer concepts with
  an animated motion preview.
- Coupled electrical-mechanical integration with voltage/current step or sine
  drive, back EMF, position-dependent force, mass/inertia, stiffness,
  damping/Q, load, stiction, and travel stops.
- Force/torque constant and gradient, acceleration, speed, displacement,
  resonance, settling, thermal force noise, Brownian motion, trajectory plot,
  and motion CSV export.
- Nanoscale screening preset with explicit MEMS/NEMS model-validity warnings.
- Temporary PCB preview, guarded named-group commit, geometry/model exports,
  and integrated model limitations.

Both packages are engineering review tools. Their reduced-order models do not
replace electromagnetic/thermal FEA, DRC, safety analysis, impedance/LCR
measurement, or prototype correlation.
