# Electrothermal studies

Open **More → Electrothermal study** in Quick PI. Choose steady saved-board
coupling or transient lumped coupling. The selected source/sinks seed the model.
The advanced input editor exposes explicit physical settings; `null` means a
required input has not been supplied. Load a study JSON to use a reviewed model.
Changing inputs clears accepted results and exports. Cancellation discards partial
results. The original PCB is read-only.

## One-click steady heating

Enable **Include Joule heating**, choose **2.5D** or **3D**, and click **Run**.
Quick PI uses the saved board geometry and the selected prescribed-current
path. The initial estimate uses generic FR-4, copper and effective air
cooling. Under **Mesh & material** you can set ambient, laminate conductivity,
effective convection, emissivity and the temperature stop. The results include
the assumptions, the ambient-temperature reference and the convergence status.
In 3D, the copper FEM exchanges heat with a board-layer thermal model. It
shows the estimated temperature on the 3D copper along with voltage, current
density and losses.

## Advanced 2.5D saved-board coupling

Supply dielectric thermal conductivity (W/m/K), copper conductivity (W/m/K), via
plating (mm), ambient (C), board convection coefficient (W/m2/K), emissivity and
the thermal grid resolution. Review the copper material-validity temperature
range and temperature cap. The initial values are assumptions, not measurements.
A saved explicit stackup, filled zones and valid closed Edge.Cuts are required.

This coupling uses the shared uniform-grid thermal kernel and circular plated
barrels. It rejects unplated drilled holes, plated slots and backdrills. The
uniform-grid approximation does not resolve plated drill-core air cavities;
barrel conduction uses its declared annular plating model. Use standalone
QuickTherm's advanced board model when drilled-void geometry matters. It does not include the newer
standalone QuickTherm advanced geometry or solver features. The advanced JSON
workflow uses 2.5D prescribed-current selections. For 3D, select the source pad group,
set a prescribed current for each independent load group under **Additional
sinks**, enable Joule heating, and click **Run**. Group contacts may share a
connector but each pad belongs to just one electrical unit.

The model transfers integrated planar/via/explicit branch watts onto overlapping
thermal cells on the matching layer. Via segment losses use an explicit uniform
axial allocation, half at each adjacent layer. The same support weights return
conductor temperatures. Local copper resistivity changes using the declared
linear temperature coefficient. Relaxed iterations retain temperature/loss
residuals and electrical, thermal and transfer balances. A final electrical rerun
checks the accepted temperature field. Cold and coupled-hot sink voltages remain
available alongside the first layer's supported temperature gradient; JSON retains
all raw layers, mesh values, sources and checks.

Series branches need `branch_heat_mappings` with a physical layer and contact
polygon. Their resistance remains fixed in this first mode. Additional component
powers use `thermal_result.components` and reviewed thermal contacts. A component
must not repeat a modeled branch's heating. Delivered load power is not
automatically heat on the PCB. Only the selected electrical nets/paths contribute
loss; omitted return paths and other energized nets remain outside coverage.

A temperature cap, invalid material range or exhausted iterations is an explained
stop, not a valid hot operating point. Missing cooling or unmapped powered regions
block the solve. Unsupported narrow source/grid coverage or subcell cutout
connections require grid refinement. Thermal properties/contact geometry and
convection/radiation remain approximate; conductor and junction temperatures are
distinct. No CFD, melting, fuse-opening or measured-board accuracy is claimed.

## Steady 3D copper feedback

The existing tetrahedral electrical solve supplies integrated watts per copper
element. Its centroid projects to an in-plane thermal cell. Interlayer losses
are shared between adjacent copper layers. Temperatures sampled with the same
weights update individual element resistivities. The result reports cold
and hot electrical quantities, convergence and energy checks. The reported
element temperatures reflect the thermal grid and should be checked under
mesh refinement. The grid masks saved unplated drill voids and slotted drills
and blocks lateral links crossing their contours. Axial heat conduction in
plated slots uses the capsule perimeter and declared plating. Electrical 3D
still requires circular plated holes on the analyzed net.

Use **Power tree** in the 3D result to review each load group's voltage,
current and delivered power. The board-copper block shows aggregate path loss.
The model shares copper between loads and therefore reports this loss once.

### Marble grouped-current check

A disposable copy of the public Marble PCB solved net `Net-(C143-Pad1)` at
a prescribed 1.2 V from grouped pads `U36.18` and `U36.19`. The separate
load units were `L16.1 + C143.1` at 160 mA and `TP4.1` at 40 mA. Their hot
drops were 0.0792 mV and 2.3448 mV. Total modeled copper loss was 0.10646 mW.
The run used a 0.8 mm electrical mesh edge, 33,238 tetrahedra, and a 32-cell
thermal grid along the longest board dimension. Heat-balance residual was
below 2e-14 W and source current residual was below 1e-10 A. The copied PCB
hash matched the original before and after. The prescribed loads and cooling
settings are a solver check.

## Lumped transient coupling

Enter source/path R/L, each load's C and ESR and the load-step conditions. Define
thermal nodes with R-theta (K/W), C-theta (J/K), initial temperature, external power
steps and limits. Map every nonzero resistor exactly once using `source`,
`path:<load-id>` or `esr:<load-id>` to a thermal node, with an explicit reference
temperature/coefficient and valid range. Thermal capacities and mappings are not
inferred from a board.

Electrical capacitor/inductor states and thermal temperatures persist between
accepted intervals. Integrated source/path/ESR dissipation heats thermal nodes;
reactive stored energy and backward-Euler numerical damping are not heat. Thermal
updates solve the independent constant-power RC interval exactly. Two-way interval
iterations start from the previous accepted states and accept an update once.
Load/power events retain their exact timestamps. L and C remain fixed.

Review electrical and thermal balances and the independent integration/exchange
refinement checks before relying on peaks or limits. A stable integration or small
reported change does not certify waveform accuracy. This is a lumped rail/node
model, not a spatial thermal transient or shared board/heatsink-storage model.

## CLI and reports

JSON intake contains exactly `mode` (`steady` or `transient`) and `study`. The
[steady example](studies/electrothermal-steady.json) is an analytical two-layer
mesh with assumed material/cooling data. The
[transient example](studies/electrothermal-transient.json) uses explicit circuit
and thermal values. Both are illustrative inputs, not fitted board models.

```text
wayricad-pi --electrothermal studies/electrothermal-steady.json --html steady.html --output steady-data.json
wayricad-pi --electrothermal studies/electrothermal-transient.json --html transient.html --output transient-data.json
```

For saved-board steady operation, supply the positional PCB and put the normal
`net`, `source_terminal`, `sinks`, `source_voltage`, `source_current_limit`,
`edge_mm` and material `options` under `study.electrical`, with thermal settings
and coupling settings alongside it. Geometry is extracted from that PCB. A
standalone explicit mesh may optionally record PCB provenance, but is still a
user-supplied model; a hash does not establish geometric accuracy.

Exit codes: 0 means the requested model's operating checks passed; 2 invalid input
or execution failure; 3 incomplete/nonconverged coupling; 4 a specified operating
limit violation. Source current limits remain diagnostic budgets, not CV/CC,
foldback, UVLO or converter-control simulations.

HTML/JSON retain source/study hashes, solver versions, model assumptions, coverage,
limits and raw results. Changed sources/settings invalidate export. Reports cannot
replace the input PCB or study. Publication errors restore the prior report pair;
an interrupted process or concurrent external file replacement is outside that
rollback guarantee. Nearly uniform temperature fields use a one-degree display
span so numerical roundoff cannot produce a false temperature gradient.
Each plugin ZIP vendors its own shared thermal
kernel; Quick PI does not require a sibling QuickTherm installation. Native
QuickTherm studies keep their existing independent behavior.
