# CalculiX 3D steady-conduction mode

`thermal_calculix.py` accepts the saved-board snapshot produced by
`collect_thermal_geometry`, the corresponding QuickTherm board view and result,
and explicit settings. It is an optional steady-conduction path. Select
**CalculiX 3D · fixed lower face** in QuickTherm's board-model controls to
run Gmsh, CalculiX, result import and top/bottom visualization in one action.
The selected board snapshot remains read-only. The board workspace shows the
imported F.Cu and B.Cu fields with cursor temperatures, probes and component
cross-selection. A model junction temperature is shown only where an explicit
RθJB field was mapped; the CalculiX deck itself does not contain packages.

```python
from quick_therm_plugin.thermal_calculix import prepare_calculix, run_calculix

settings = {
    "gmsh_mesh_size_mm": 0.5,
    "dielectric_k_w_mk": 0.3,
    "copper_k_w_mk": 385,
    "bottom_temperature_c": 20,
}
manifest = prepare_calculix(geometry, view, result, settings, "candidate-thermal")
if manifest["status"] == "deck_ready":
    manifest = run_calculix("candidate-thermal")
```

The independent QuickTherm CLI can prepare the same deck from a saved board
and a reviewed JSON config that maps `field_map.power_w` and contains
`calculix_settings`. For example:

```text
wayricad-therm C:/Projects/Example/board.kicad_pcb --config thermal.json --calculix-dir C:/Projects/Example/thermal-deck
```

Add `--run-calculix` to invoke `ccx`; use `--calculix-exe` when it is not on
PATH. A config with `"thermal_model_kind": "calculix"` runs the full workflow
and puts its checked temperature field in `thermal_network`. It may omit
`--calculix-dir` for temporary working files, or set it to retain the complete
deck, mesh, FRD, imported field and manifest. The JSON response includes the
solver status and lower-face heat balance. A board with vias or mounting holes
is rejected until those contacts have an explicit meshed thermal model.

`prepare_calculix` creates a new output directory and refuses to overwrite
one. It checks the saved PCB SHA-256 when the snapshot includes source identity.
The directory always contains `board.geo` and `manifest.json`. With the Gmsh
executable on PATH, or its Python package in the active KiCad runtime, it
generates `board.msh` (ASCII MSH 2.2) and
`board.inp` (CalculiX). `run_calculix` runs `ccx`, reads the final complete
ASCII `NDTEMP` block from `board.frd`, checks that every deck node is present,
checks the prescribed lower-face temperatures and integrates the lower-face
heat flux against injected power. Rejected or incomplete results do not appear
as solved temperatures. Accepted results are projected only inside the Gmsh
triangles into `board_field.json`; the corresponding source hash stays in the
manifest. The UI and reports use this imported field, never an unparsed FRD.

The Gmsh mesh follows the closed Edge.Cuts outline and board cutouts in XY.
Each triangle is extruded through explicit copper and dielectric intervals to
form conforming `DC3D6` wedges. Coordinates are converted from millimetres to
metres. A copper wedge uses copper conductivity when its triangle centroid
falls in saved filled copper on that layer; other wedges use the specified
dielectric conductivity. The entire lower face is fixed at
`bottom_temperature_c`; all other faces are adiabatic. Positive component
power is distributed across top nodes by the area of triangles whose centroids
fall inside each saved footprint bounding box. The deck checks that the
distributed watts equal the component input watts.

This is a bounded approximation. It rejects plated barrels, drilled pads,
mounting contacts, bottom sources, heatsinks, selected pad-contact models,
convection, and radiation. It has no package junction or thermal contact
resistance model. Thin copper and small source footprints can be missed by
centroid classification; source footprints with no selected triangle cause a
refinement error. A mesh refinement study and comparison to a measured or
analytical reference are required before engineering use. A native KiCad 10
test runs Gmsh and CalculiX 2.23 on a uniformly heated plate, checks the
analytical temperature rise and heat balance, and verifies the imported top
and bottom views. Other board geometries and cooling conditions are not
qualified by that fixture.

Gmsh syntax and MSH selection follow the [Gmsh reference manual](https://gmsh.info/doc/texinfo/gmsh.html).
`DC3D6`, `*HEAT TRANSFER`, thermal degree of freedom 11 and `*NODE FILE NT`
follow the [CalculiX manual](https://www.dhondt.de/ccx_2.22.pdf).
