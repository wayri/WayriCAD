# WayriCAD PCB / Foil Heater Designer

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD PCB / Foil Heater Designer icon">

## Capabilities

- Designs series-connected serpentine, zoned-raster, and concentric-spiral copper heaters.
- Adjusts regional trace resistance to bias local Joule heating.
- Continues multilayer heater paths through transition vias.
- Previews geometry and runs a steady-state 2D conduction/convection thermal model.
- Reviews existing copper, zones, and keepouts before applying a recoverable named group.
- Supports persistent heater-group undo after reopening the plugin.

## Limitations

- The thermal model is reduced-order and steady-state; it does not establish thermal performance or safety acceptance.
- It does not solve enclosure airflow, radiation, anisotropic laminate, adhesive interfaces, attached masses, or closed-loop control dynamics.
- Generated terminals must be connected afterward, and KiCad DRC remains the final geometry check.
- Fabrication requires coupled-solver and physical-prototype validation of temperature, current density, materials, airflow, and control stability.

## Overview

Design series-connected serpentine, zoned-raster, or concentric-spiral copper
heaters. Regional resistance factors narrow or widen the trace to bias local
Joule heating, while multilayer mode continues the path through transition
vias. The generated geometry can be inspected in the window, simulated, reviewed for placement, and applied to the PCB only after review.

The thermal preview is a reduced-order steady-state 2D conduction/convection
model. Validate maximum temperature, copper current density, laminate limits,
adhesive behavior, airflow, attached masses, and control stability using an
appropriate coupled solver and physical prototype before fabrication.

Window previews do not create board geometry. Apply writes the reviewed geometry as a recoverable group. Committed heaters
use persistent named groups, and the latest WayriCAD heater commit can be undone
after reopening the plugin.

Placement review now checks existing copper, zones and keepouts before creating a group, including copper on the selected net that would short around the designed conductor. Pad, text and zone bounding boxes are reserved conservatively. Choose a clear area and connect the generated terminals afterwards; KiCad DRC remains the final geometry check. Redo repeats the placement check.

Native operational validation uses `python tools/validate_marble_operations.py` from the suite root. It exercises review, apply, undo/redo, preserved net assignment, native saved-board reload and full DRC on explicit isolated test coupons in copies of Marble. These coupons are validation fixtures, not proposed Marble modifications.


## Native interface

![Native WayriCAD PCB / Foil Heater Designer window](help-workflow.png)

Generated serpentine preview from the documentation fixture. Geometry preview alone does not establish thermal performance or placement acceptance.

The installed package includes [offline help](help.html) with its workflow and limitations.
