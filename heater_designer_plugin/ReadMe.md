# KiWay PCB / Foil Heater Designer

Design series-connected serpentine, zoned-raster, or concentric-spiral copper
heaters. Regional resistance factors narrow or widen the trace to bias local
Joule heating, while multilayer mode continues the path through transition
vias. The generated geometry can be inspected in the window, simulated, shown
temporarily on the PCB, and committed only after review.

The thermal preview is a reduced-order steady-state 2D conduction/convection
model. Validate maximum temperature, copper current density, laminate limits,
adhesive behavior, airflow, attached masses, and control stability using an
appropriate coupled solver and physical prototype before fabrication.

Temporary board geometry is removed when the window closes. Committed heaters
use persistent named groups, and the latest KiWay heater commit can be undone
after reopening the plugin.
