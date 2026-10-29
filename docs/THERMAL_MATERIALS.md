# Reviewed thermal material references

The shared offline library supplies explicit thermal inputs for QuickTherm and
Quick PI's electrothermal setup. Opening a material picker changes no study.
Choose a reference, read its source and conditions, check the properties to use,
edit only known values, and acknowledge applicability before **Apply selected
properties**. Unknown properties remain blank. Overrides require a source and
conditions review note and retain the original preset provenance.

QuickTherm exposes **Dielectric material…** and **Copper material…** in **Board
heat model**. They apply selected conductivity and optional volumetric capacity
to the corresponding layered/3D material inputs; they do not change the
thin-sheet effective in-plane conductivity. The copper and dielectric fields
remain independent. Quick PI's electrothermal dialog offers the same buttons
for conductivity in its steady saved-board model. Lumped transient R/C values
remain explicit. Applying a selection clears stale results and exports.
`material_library` in the QuickTherm request or canonical PI study retains the
reviewed selection and target bindings. Editing a selected numerical value later
removes that selection's active provenance, so an old preset cannot describe
new manually edited values.

| Reference | Conductivity W/(m·K) | Other available SI data | Evidence and conditions |
|---|---:|---|---|
| Copper, illustrative | 385 | Volumetric capacity 3,450,000 J/(m³·K) | Inherited repository assumptions; grade, temperature and validity unknown |
| Generic FR-4, illustrative | 0.3 | Volumetric capacity 1,800,000 J/(m³·K) | Inherited repository assumptions; no identified laminate or anisotropy |
| Isola 370HR | 0.4 | Heat capacity unknown | Manufacturer typical, ASTM E1952; temperature/direction unstated |
| Rogers RO4003C | 0.71 | Density 1790 kg/m³ at 23 °C | Conductivity at 80 °C, ASTM C518; direction unstated |
| Rogers RO4350B | 0.69 | Density 1860 kg/m³ at 23 °C | Conductivity at 80 °C, ASTM C518; direction unstated |
| Henkel GAP PAD TGP 1500 | 1.5 | Density 2100 kg/m³; specific heat 1000 J/(kg·K); derived volumetric capacity 2,100,000 J/(m³·K) | Manufacturer typical cured/bulk material; ASTM D5470/D792/E1269; row temperatures unstated |

The [Isola data sheet](https://www.isola-group.com/wp-content/uploads/data-sheets/370hr.pdf)
is dated April 15, 2021 (footer Revision C). The
[Rogers data sheet](https://www.rogerscorp.com/-/media/project/rogerscorp/documents/advanced-electronics-solutions/english/data-sheets/ro4000-laminates-ro4003c-and-ro4350b---data-sheet.pdf)
is revision 1592 080322, PUB# 92-004; its typical-values table supplies the
conductivity and density conditions. The
[Henkel data sheet](https://datasheets.tdx.henkel.com/BERGQUIST-GAP-PAD-TGP-1500-en_GL.pdf)
is dated October 2020. These primary references were checked October 29, 2026.
The Henkel SI conversions multiply g/cm³ by 1000 and J/(g·K) by 1000; the
volumetric capacity is the explicit product of density and specific heat.

Manufacturer typical values are reference data, not guaranteed application
properties. A measurement temperature does not define an operating range or
justify constant-property extrapolation. No emissivity, electrical resistance,
CTI, dielectric strength, thermal limit or material validity range is inferred.
Conductivity in a laminate is not the effective conductivity of an assembled
copper-filled board. Interface-pad conductivity alone does not establish contact
resistance, compression or assembly performance. Enter geometry, boundaries,
contacts and unknown storage values separately and retain numerical refinement.

## Shared API

`wayricad_runtime.thermal_materials.list_materials(category=None)` returns detached
records. Categories are `metal`, `laminate`, `interface` and `custom`.
`get_material(id)` returns one reference. Every known property carries its SI
unit, conditions, test method and basis (`typical`, `derived_typical`,
`illustrative` or `user_override`).

`review_material(id, selected=[property], overrides={property: value},
reviewed=True, review_note='…')` returns a reviewed schema-1 selection.
`validate_material_selection(selection)` rechecks units, finite positive values,
source identity and override status. `apply_material_selection(settings,
selection, bindings)` returns a copy with only the explicitly bound selected
numeric fields changed. The caller retains the full selection in study
provenance. These functions have no native GUI dependency.

The native `ThermalMaterialDialog(parent, properties=[…], category=None,
initial_id=None)` exposes `.dialog` and sets `.selection` only on explicit
acceptance. Property keys are `thermal_conductivity_w_mk`,
`volumetric_heat_capacity_j_m3k`, `density_kg_m3` and `specific_heat_j_kgk`.
Callers limit the picker to properties their model consumes and bind targets
explicitly; the picker cannot silently apply one material to both copper and
dielectric, or convert a reference value into a qualification claim.
