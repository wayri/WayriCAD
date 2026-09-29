# QuickTherm board screening model

QuickTherm starts with a read-only, steady-state **lumped estimate** for selected board
components; its optional thin-sheet network solves an approximate board field. Map the actual saved KiCad
footprint property names before running. No default power or thermal resistance
is supplied, and fields are never guessed from reference prefixes or values.

The native tab and exported HTML include saved-board top and mirrored bottom
views, a rotatable illustrative 3D outline, sortable component results and
min/max/mean/median **solved junction** analytics. Side-specific junction
contours interpolate between solved component estimates within supported
geometry; they are not board-surface predictions. Unsupported areas are blank.
Select a map marker or result row to select the exact footprint in the
originating PCB Editor.

The optional thin-sheet board model takes effective in-plane conductivity,
saved thickness, emissivity, board/sink air speeds and exposed virtual-sink
areas. It solves lateral conduction and a heat balance against approximate
convection and gray-body radiation. Top and bottom share one cell temperature;
the mesh resolution is selectable (48 long-axis cells by default; up to 80 in
the UI). Power spreads across the saved footprint bounds when available,
conserving each component's total dissipation. Compare multiple mesh densities
for local peaks; smooth plotting does not establish numerical convergence.
There is no through-thickness gradient, copper/via detail or CFD airflow. It
does not reuse the lumped RθJA value as a component-to-board resistance.
Model junction estimates require explicit component-to-board RθJB or the
existing mapped RθJC plus contact resistance for a virtual sink. Their table
cells are blank without those paths; legacy RθJA is not substituted.

## Layer-resolved board screen

Choose **Copper layers + vertical paths** in the optional board model to use
the saved KiCad stackup, filled copper geometry, traces, pads and plated via
barrels. Enter measured dielectric conductivity (W/m·K) and fabrication via
plating thickness (mm); copper conductivity is editable. KiCad's dielectric
constant is electrical data and is never substituted for thermal conductivity.
The mesh resolves lateral copper conduction, dielectric conduction between
copper midplanes and axial barrel conduction. Top/bottom convection and
gray-body radiation are approximate. Virtual heatsinks remain available and
require explicit exposed area; an optional sink-to-board shunt is represented
only when its resistance is supplied. Results contain a selectable temperature
map for every copper layer, per-contact heat flow and a signed energy balance.

The **Copper simplification** choice samples each saved copper polygon with
0, 0.5 or 1 cell of subcell coverage. It does not blur temperatures or create
connections across separate copper islands. Compare mesh sizes and inspect
small gaps before trusting a local peak. An unfilled zone, missing saved
stackup, unsupported slot/backdrill or changed source file blocks the layered
solve rather than silently substituting nominal geometry.

To model a fixture holding one or more drilled holes at a stable temperature,
select the exact hole records in the optional model pane, then enter its
setpoint (for example 10 °C) and contact resistance (K/W). A plated hole is
linked through its saved land and barrel geometry. An unplated hole needs the
explicit **Mechanical fixture contacts selected NPTH holes** option; that
couples the fixture to the board dielectric at the selected location and does
not invent a ground-plane connection. The net name alone never creates a heat
sink. The reported fixture flux is positive when heat leaves the board and
negative when heat enters it. The shared setpoint/contact controls currently
apply to all selected holes; use separate studies for differing conditions.

This finite-volume model is a screening approximation. Footprint bounds proxy
component heat injection; package spreading, copper-to-barrel contact detail,
anisotropic laminates, edge losses, airflow fields, view factors, thermal
transients, electrical-loss feedback and qualification against measurements
remain unresolved. Whole-circuit transient and coupled electrothermal work is
tracked in [SPIKE #1](https://github.com/wayri/SPIKE-Main/issues/1).

| Mapping key | Meaning | Accepted field values |
|---|---|---|
| `power_w` | Dissipated power at the operating point | `0.5`, `500mW`, `0.5 W` |
| `theta_ja_air_k_per_w` | Junction-to-ambient resistance for **this board and airflow** | `40`, `40 K/W`, `40 °C/W` |
| `theta_jb_k_per_w` | Junction-to-board resistance at the assumed heat path | `10`, `10 K/W`, `10 °C/W` |
| `theta_jc_k_per_w` | Junction-to-case resistance for an assigned heatsink | `3`, `3 K/W`, `3 °C/W` |

Bare power values are watts; bare thermal-resistance values are kelvins per watt.
The mapping is case-sensitive. The saved board's custom footprint properties
must contain the requested fields. Power must be nonnegative and resistances
strictly positive. Enter zero power explicitly for a selected non-dissipating
part. Select the intended dissipating references to define the study scope;
components outside that scope are not counted.

An adapter with a loaded `pcbnew.BOARD` can call:

```python
from quick_therm_plugin.quick_therm import analyze_board

field_map = {
    'power_w': 'Dissipation',
    'theta_ja_air_k_per_w': 'Theta JA',
    'theta_jb_k_per_w': 'Theta JB',
    'theta_jc_k_per_w': 'Theta JC',
}
air = analyze_board(board, field_map, environment='air', ambient_c=25,
                    references=['U1', 'U2'])
vacuum = analyze_board(board, field_map, environment='vacuum', ambient_c=25,
                       references=['U1', 'U2'],
                       vacuum_board_to_environment_k_per_w=30)

sink = {'U1': {'shape': 'straight_fin', 'width_mm': 20,
               'height_mm': 12, 'depth_mm': 15,
               'contact_k_per_w': 1, 'theta_sa_air_k_per_w': 8}}
air_with_sink = analyze_board(board, field_map, environment='air', ambient_c=25,
                              references=['U1', 'U2'], heatsinks=sink)
```

The air estimate is `Tj = Tamb + P × RθJA_air` for each part. The mapped
`RθJA_air` should be characterized for the actual board, airflow, mounting and
power distribution. A generic datasheet RθJA measured on a different test board
can be substantially misleading. Components are independent in this mode;
there is no calculated board temperature or inter-component coupling.

The vacuum estimate has one isothermal board node:
`Tboard = Tamb + ΣPboard-path × Rboard→environment`, then
`Tj,i = Tboard + Pi × RθJB,i`. The **positive** board-to-environment resistance
must be supplied from a separate thermal characterization for the actual vacuum
assembly, including its radiation and mechanical conduction paths. It cannot
be inferred from in-air RθJA. An isolated board with no thermal path has no
finite steady-state temperature in this model. Vacuum mode refuses an incomplete
scoped field set so missing heat loads cannot silently lower every estimate.

## Optional virtual heatsinks

Assign a heatsink by component reference with a `heatsinks` mapping. Supported
visual shapes are `straight_fin`, `pin_fin`, `radial_fin`, `plate`, and
`resistance_only`. For the first four shapes, positive `width_mm`, `height_mm`,
and `depth_mm` are required; they are optional for `resistance_only`. Geometry
supports a preview but **does not determine thermal resistance**. Supply a
positive `contact_k_per_w` and environment-specific
`theta_sa_air_k_per_w` or `theta_sa_vacuum_k_per_w`; also map a saved footprint
field for `theta_jc_k_per_w`. Without those values, no heatsink temperature is
calculated. If every scoped component has a heatsink, RθJA/RθJB mappings and
the board-to-environment vacuum resistance are unnecessary.

For a heatsink part, `Tj = Tamb + P × (RθJC + Rcontact + RθSA)`.
The sink-to-ambient resistance must characterize the actual orientation,
airflow, temperature, and—in vacuum—radiation/conduction path. Air resistance
cannot be reused in vacuum. Each heatsink is an **independent path** and its
power is excluded from the shared board-node sum. Parallel case-to-board heat
flow is omitted; this avoids double counting but may miss important coupling.
Choose the path model appropriate to the component assembly or use a qualified
multinode thermal solver. The result labels each component's heat path and
reports `board_path_power_w` separately from total scoped power.

Air mode permits partial coverage but records every excluded component and marks
`coverage.complete = false`; the listed temperatures then describe only the
solved components. The returned JSON contains the mapping, scope, model,
assumptions, coverage, total known power, board temperature where applicable,
and per-component temperature rise. An interface should display incomplete
coverage prominently and avoid presenting it as board-wide verification.

These are screening estimates, **not** qualified thermal simulation. The lumped
mode omits spatial board gradients; the layered mode approximates copper heat
spreading and explicitly selected mounting contacts but still omits detailed
package/contact geometry, temperature-dependent properties, feedback into
dissipation, transient heat capacity, chamber view factors and spatial airflow.
`Rboard→environment` in the lumped vacuum mode is an effective linearized
value for the intended operating point; it can change with temperature. Check
critical designs against a qualified thermal model or measurements. Ambient
temperatures are °C, power is W, thermal resistance is K/W, and temperature
rises are K.
