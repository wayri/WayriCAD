# WayriCAD Planar Magnetics & Actuator Workbench

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD Planar Magnetics &amp; Actuator Workbench icon">

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#getting-started) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run planar-magnetics -- --help` |

CLI scope: JSON winding analysis; copper placement remains in the GUI. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

## Getting started

1. Save the PCB and open the Planar Magnetics PCM plugin. Choose a winding geometry, layer arrangement, net assignments and a clear placement area.
2. Enter dimensions, conductor properties and the material/core information needed by the selected model. Leave unavailable quantities unknown.
3. Use **Analyze** to inspect geometry and electrical estimates. Field, core, motor and coupled-motion workbenches have their own inputs and limits below.
4. Review before applying a winding group. Connect its terminals and run KiCad DRC. Export model evidence separately; estimates do not establish physical performance.

## Capabilities

- Generate rectangular/circular planar windings with multilayer transitions, primary/secondary nets and reviewed, recoverable PCB placement.
- Estimate winding electrical properties and reduced actuator motion; inspect dimensioned cores, B-H sweeps, reluctance, saturation and ideal-gap force.
- Solve explicit linear axisymmetric winding fields, mutual coupling and leakage; inspect mesh, B/H and convergence evidence.
- Compute explicit-dielectric coaxial capacitance matrices and partial single-layer PCB sidewall capacitance.
- Synthesize logical concentrated/distributed/chorded motor windings with balanced 2–12-phase presets, a dimensioned annular phase/slot preview, EMF, ideal-current torque/force and phase-event references.
- Run supported equivalent-circuit AC/DC and motor-mechanics transient simulations using KiCad ngspice; export project-local HTML, JSON, SPICE, CSV and plots.

## Limitations

- Field FEM covers explicit linear axisymmetric geometry; arbitrary STEP field meshing, nonlinear full-field and frequency-dependent eddy/core-loss extraction are not implemented.
- Capacitance models have explicit voltage, dielectric and geometry assumptions; PCB sidewall estimates are partial, not total winding capacitance or SRF validation.
- Motor layouts are logical connections, not manufactured stator or routed PCB geometry. Phase events are not inverter gate commands.
- The motor winding workbench’s ideal-current transient omits winding-voltage dynamics, current control, cogging, saliency, saturation and end effects.
- Reduced force/motion models and MEMS/NEMS presets need material, boundary and prototype validation; native DRC is still required for generated copper.

## Overview

Generate rectangular or circular planar windings across as many as 16 copper
layers with series transitions, stitched vias, separate primary/secondary PCB
nets, independently layered secondary turns, and an extensible JSON magnetic-core catalog. The workbench
estimates DC/AC resistance, inductance, capacitance, self resonance, Q, copper
and core loss, saturation, coupling, field, force, and magnetic-torquer torque.

The coupled motion solver integrates coil current and a one-degree-of-freedom
mechanical model. Inputs include moving mass or rotary inertia, restoring
stiffness, damping or mechanical Q, initial magnetic gap, hard travel limits,
external load, static friction, waveform, drive frequency, simulation duration,
time step, and temperature. Results include force or torque, transduction
constant, force gradient, acceleration, speed, displacement, resonance,
settling, thermal force-noise density, and Brownian displacement.

Actuator modes cover voice coils, linear solenoids, PCB coil motors, and PCB
magnetic torquers. Macro and nanoscale screening presets are provided. The
nanoscale preset is not a fabrication signoff model: it omits rarefied-gas and
squeeze-film damping, adhesion, stiction physics, Casimir and van der Waals
forces, process stress and geometry variation, nonlinear material properties,
multimode coupling, readout back-action, and quantum effects. Use
process-calibrated electromagnetic/structural/fluid/thermal FEA and measured
device parameters before fabricating MEMS or NEMS hardware.

Preview stays in the window and does not change the PCB. Apply checks that the board and settings still match the review. Accepted windings
are stored in persistent named groups, allowing the latest WayriCAD commit to be
undone after reopening the workbench.

Placement review now checks existing copper, zones and keepouts before creating a group, including copper on the selected net that would short around the designed conductor. Pad, text and zone bounding boxes are reserved conservatively. Choose a clear area and connect the generated terminals afterwards; KiCad DRC remains the final geometry check. Redo repeats the placement check.

**Analyze** reviews winding geometry and electrical estimates. **Run Coupled Motion Simulation** separately runs the bounded dynamics solver, so mechanical duration/step limits cannot block ordinary winding placement.

Native operational validation uses `python tools/validate_marble_operations.py` from the suite root. It exercises review, apply, undo/redo, preserved net assignment, native saved-board reload and full DRC on explicit isolated test coupons in copies of Marble. These coupons are validation fixtures, not proposed Marble modifications.


## Native interface

![Native WayriCAD Planar Magnetics & Actuator Workbench window](help-workflow.png)

Generated coil preview from the documentation fixture. Reduced engineering estimates require the stated geometry and material assumptions.

The installed package includes [offline help](help.html) with its workflow and limitations.

## Custom cores, saturation and STEP inspection

**Core tools** adds dimensional core editing, measured B-H tables, current/saturation, incremental-inductance and ideal-gap-force plots, transformer volt-second checks, and CSV export. Optional FreeCAD STEP inspection shows solid geometry, dimensions and volume while requiring explicit magnetic dimensions/material inputs. See [equations, workflow, installation and limits](MAGNETICS_MODELS.md).

![Native magnetic circuit sweep with synthetic B-H material](help-core-sweep.png)

These are magnetic-circuit calculations and a STEP surface preview; full-field transformer/actuator FEA remains unimplemented.


**Axisymmetric field** adds a real linear FEM subset for dimensioned annular
windings and optional bore cores. Inspect native |B|/Br/Bz maps, mesh cells,
energy-derived inductance and three-case mesh/air-domain convergence. This does
not import arbitrary STEP into a field solve or replace nonlinear transformer FEA.

![Native axisymmetric field visualization](help-axisymmetric.png)

## Extract coupling and export equivalent circuits

After **Preview**, use **More → Equivalent model & report**. The review shows Rdc, incremental L, B/H, supplied magnetic path length, and core/gap reluctance for the magnetic-circuit model. Enter known capacitances in pF; blanks remain unknown and are omitted. Transformer export requires secondary Rdc. Supplied k is explicitly an assumption; short-circuit leakage is L(1−k²), not a fabricated geometric extraction.

Choose **Extract coaxial coupling** for a genuine linear FEM extraction. Define two non-overlapping annular windings; core and mesh controls are on their own tab. Independent unit-current excitations on a shared mesh compute L11, L22 and mutual M, then k and both short-circuit leakage inductances. The native field includes both winding outlines, a quantitative B legend and cell B/H probing. The displayed field is primary 1 A, secondary open. This independent geometry is not inferred from the planar PCB winding; enter its primary and secondary Rdc explicitly.

![Native two-winding field extraction](help-coupled-field.png)

The inductance matrix must be reciprocal and positive definite; |k| must be below one. The [independent mutual-inductance reference](../docs/MAGNETICS_VERIFICATION.md) checks against Neumann/elliptic-loop integration. Matrix checks and that reference do not certify a chosen model's air-boundary or mesh convergence. Compare refined meshes and larger air domains; no nonlinear core, frequency-dependent leakage, electrostatic capacitance or conductor loss is extracted by this field subset.

![Reviewed equivalent circuit and assumptions](help-equivalent.png)

**Export report + SPICE** creates a unique folder under `PROJECT/reports/wayricad-magnetics/`, containing `model.html`, `model.json`, `model.cir` and, for field extraction, `field.json`. The HTML is fully local, includes a circuit diagram and solved-field SVG, and records units, missing data, assumptions and the saved-board hash. Saved-board changes invalidate export context. Existing files and the PCB are never overwritten. A redirected default report folder outside the project is rejected.

Supported SPICE subcircuits are incremental inductors, two-winding coupled inductors, constant-Bl linear actuators and explicit-parameter brushed DC motors. For a DC motor supply Kt=Ke in SI, rotor inertia, rotational damping and optional torsional stiffness. `VEL` is linear speed in m/s; `OMEGA` is angular speed in rad/s. Both models use reciprocal back EMF and force/torque, with zero initial state. Motor constants are supplied, not extracted; BLDC commutation, rotating fields, cogging, saturation and position-dependent dynamics are not modeled. Optional interwinding C is one lumped capacitor between dotted terminals, not a distributed insulation model.

Validation: 33 focused magnetics tests pass, including passivity, analytic reluctance, units, explicit missing data and unique exports. An exported DC motor was also executed with KiCad's bundled ngspice: 1 V, R=0.2 Ω, Kt=Ke=0.1 and damping=0.001 gives 9.8039215686 rad/s, matching the analytical DC operating point. This does not establish transient accuracy for an arbitrary motor.

## Run with KiCad's SPICE engine

The equivalent-model dialog now has **Run simulation**. Review the model first, then set drive voltage and (for transformers) load resistance. Inductors and transformers run an actual 10-points/decade AC sweep through KiCad's bundled ngspice library in an isolated process. The native plots show input impedance and transformer gain or impedance phase. Mechanical equivalents use a DC operating point and report current, speed, force/torque and converted power; frequency controls are disabled. Hover the result status for the engine library path and version log.

![Actual KiCad-ngspice AC simulation](help-spice-simulation.png)

No separate SPICE installation is required. If KiCad simulation support is unavailable, the plugin reports the missing engine instead of substituting results. `WAYRICAD_KICAD_NGSPICE` can identify the shared library used by KiCad. The calculation is bounded and isolated so an engine failure does not crash the plugin. Changes to the model or simulation inputs clear stale results.

Export after simulation adds `simulation.json` containing the generated deck, complex vectors, engine provenance and numerical results; the local HTML includes the actual simulation plot. These are simulations of the reviewed lumped equivalent: incremental L and Rdc are constant, only explicitly supplied C is included, and nonlinear saturation, frequency-dependent core loss, eddy currents and motor commutation remain excluded. Mechanical DC results are steady state; a restoring spring can make final speed zero.

## Compute capacitance from stated geometry

**Equivalent model & report → Compute capacitance** now offers two explicit-dielectric models. εr starts blank and must be supplied; it is never inferred from magnetic permeability.

- **PCB sidewalls** uses the actual generated single-layer rectangular winding and adjacent parallel sidewall overlaps. It integrates pair capacitance against squared local voltage difference, assuming voltage varies linearly with conductor arc length. The result is a **partial sidewall contribution**, excluding fringing, broad-face coupling, substrate interfaces, other layers and nonadjacent turns. Multilayer and curved windings are rejected. This is not total capacitance or an SRF validation.
- **Coaxial FEM** solves two equipotential annular conductors in a homogeneous dielectric and explicitly grounded outer enclosure. It produces a reciprocal Maxwell capacitance matrix and a native potential preview. Geometry is independent of the PCB; an existing coaxial magnetic model can seed its dimensions. No arbitrary STEP or 3D electrostatic extraction is claimed.

![Actual generated PCB sidewall contribution](help-capacitance-pcb.png)
![Native coaxial electrostatic FEM and terminal mapping](help-capacitance.png)

Computed values are not applied until the displayed potential assumptions are explicitly accepted. For the coaxial model, P and S represent the equipotential windings and the grounded enclosure is tied to primary return N. SPICE preserves all three passive branches: C(P,S), C(P,N) and C(S,N). This is a common-mode surrogate, not a distributed differential transformer winding-capacitance extraction. Review mesh and enclosure sensitivity before using it. Do not combine differently assumed partial models blindly.

Manual pF overrides remain available and remove the corresponding computed provenance/environment network. Project reports preserve dielectric, dimensions, assumptions, matrix and evidence; electrostatic field JSON and an HTML potential SVG accompany the model. The independent numerical checks include analytic coaxial capacitance, reciprocity/energy, dielectric scaling, sidewall geometry scaling and equality of Maxwell-matrix energy with exported SPICE capacitor-network energy.

## Motor winding, EMF and phase timing

Open **Core tools → Motor winding / EMF**. The separate workbench synthesizes logical two-layer coil connections for distributed full-pitch, concentrated tooth and chorded windings, with balanced presets for 2–12 phases. Review slots, poles, coil pitch, turns and phase balance before simulation. In rotary mode, enter preview inner/outer radii and use **Show winding phase** to inspect one phase or all phases. The annular view draws every start/return slot as a phase-coloured loop inside a separate radial display lane, labels selected-phase polarity and slot endpoints, and shows inner/outer diameters. It is a **logical projection**: lane separation does not allocate real copper layers or prove trace clearance, winding resistance, end-turn routing, pad placement or manufacturability. The model's EMF and torque calculations do not use the preview radii. The layout and exported `coils.csv` describe slot/phase/polarity assignments, **not manufactured stator geometry, end-turn packing or routed PCB copper**.

![Earlier logical winding layout example](help-motor.png)
![Phase EMF and ideal-current effort](help-motor-emf.png)

Supply the fundamental air-gap B and active geometry, or use the explicitly limited PM magnet/gap estimate. Wound-field mode requires supplied B; no rotor excitation circuit is solved. Rotary and linear modes show phase EMF, torque/force and constant-speed zero/peak timing events. Timing is a reference, not PWM, commutation or dead-time instructions. Even-phase presets use independent H-bridge phase axes, not an assumed shared neutral. The [model equations and research review](../docs/MOTOR_MODELS.md) state exactly which baseline is implemented.

**Run KiCad SPICE** solves the mechanical transient with ideal position-synchronous quadrature currents, inertia/mass, damping and a signed load. This is actual bundled-ngspice mechanics; phase flux/EMF are evaluated at the resulting position. It does not solve winding voltage dynamics, an inverter, current control, saliency, cogging, saturation, losses or finite-stroke end effects.

![Actual KiCad-SPICE motor mechanics](help-motor-motion.png)

**Export reviewed report** creates a unique project folder under `reports/wayricad-magnetics/motor-*`, with model/input/evidence JSON, logical coil CSV, all native plot SVGs, HTML and the mechanical SPICE deck when simulated. Changed inputs invalidate results; a changed saved board requires review before export. Native validation covered the 36-slot/4-pole/3-phase layout, 12 reference phase events, a 2,015-point real ngspice transient (final speed 5.69565358 rad/s), linear force/EMF review and complete project reports. These are numerical reference checks, not measured motor validation.


## Resize the workspace and find help

Drag the settings/preview dividers in Design and Actuator to enlarge the controls or geometry. Actuator plots and result tables also have an adjustable divider; scrolling a control area does not change its numerical assumptions.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.

## Implemented methods and research basis

The table below is an implementation inventory, not a list of planned features. The detailed derivations and model contracts are in [MAGNETICS_MODELS.md](MAGNETICS_MODELS.md); numerical reference checks and their tolerances are in [MAGNETICS_VERIFICATION.md](../docs/MAGNETICS_VERIFICATION.md).

| Implemented method or workflow | Source and numerical contract | Assumptions, units and limits | Existing verification |
|---|---|---|---|
| Planar winding geometry and guarded board placement | [analysis.py](analysis.py) constructs rectangular segments or a sampled circular spiral, adds series vias between layers and totals conductor length. [placement.py](placement.py) previews the native KiCad geometry, checks the board outline, copper, zones, keepouts and conservative pad/text/zone bounds, then applies an undoable group. | Geometry inputs are in mm and converted to SI for analysis. The circular path is a polygonal sample, not an exact arc. Multiple layers are series-connected; routing, terminal connections and fabrication clearances remain the designer's responsibility. Collision screening is conservative and is not KiCad DRC. | High-level generation, coupling, via and rejection paths are covered in [test_heater_magnetics.py](../tests/test_heater_magnetics.py); review separation is checked in [test_winding_review.py](tests/test_winding_review.py). Native apply/undo/reload/DRC evidence is produced by `tools/validate_marble_operations.py`, not by the analytical tests. |
| Copper and air-core winding estimates | [analysis.py](analysis.py) computes `Rdc = ρℓ/(wt)` and divides resistance by `layers²` for identical parallel layers. Skin depth is `δ = sqrt(2ρ/(ωμ0))`; the implemented AC factor is `max(1, t/(2δ))` times a project-specific proximity multiplier. Air-core inductance uses the circular or rectangular current-sheet coefficient form `L = μ0 N² davg c1/2 [ln(c2/fill) + c3 fill + c4 fill²]`. Legacy capacitance is `ε0 εr ℓw/gap` times a layer multiplier; `SRF = 1/(2πsqrt(LC))` and `Q = ωL/Rac`. | SI internally: Ω·m, m, H, F and Hz. Uniform trace cross-section, identical parallel layers and uniform current are assumed. The proximity multiplier and legacy capacitance/layer factor are explicitly **project heuristics**; they are not field solutions or literature-validated PCB-loss/capacitance models. Skin effect is first order; vias, pads, surface roughness, return paths, dielectric interfaces, fringing and radiation are omitted. | Geometry/electrical scaling and transformer/actuator integration are exercised in [test_heater_magnetics.py](../tests/test_heater_magnetics.py). The current-sheet inductance coefficients are adopted from Mohan et al.; the paper's reported accuracy is for its studied spiral geometries and must not be transferred to this whole workflow. |
| Nonlinear magnetic circuit, incremental inductance, volt-seconds and ideal gap force | [magnetic_circuit.py](magnetic_circuit.py) solves `NI = H(B) le + B gap/μ0` by analytic inversion of the monotone, piecewise-linear supplied B-H curve, without iterative extrapolation. Differential inductance is `N² Ae/(le dH/dB + gap/μ0)`. Transformer flux swing is `ΔB = V ton/(N Ae)`; the one-gap uniform-pole estimate is `F = B² Ae/(2μ0)`. [step_core.py](step_core.py) and [step_core_worker.py](step_core_worker.py) only inspect STEP solids, bounds and volume. | `Ae` in m², `le` and gap in m, current in A, L in H and force in N. Signed current produces signed B/flux. The B-H curve is static and anhysteretic; outside-table operation is reported rather than silently extrapolated. No fringing, leakage, hysteresis loop, eddy-current distribution, temperature dependence or distributed saturation is solved. Force is unavailable without a valid gap/pole area. STEP inspection does not infer a magnetic path, gap, material or winding. | [test_magnetic_circuit.py](tests/test_magnetic_circuit.py) checks linear reluctance, a nonlinear knee, signed current, saturation limits, volt-seconds, force and differential L. [test_equivalent.py](tests/test_equivalent.py) checks reluctance/field units and energy mapping. |
| Reduced winding/core and one-degree-of-freedom actuator analysis | [analysis.py](analysis.py) maps winding and optional core results into transformer coupling, solenoid/voice-coil/torquer force or torque and a coupled electrical-mechanical time model. The transient integrates RL/back-EMF and one mechanical coordinate with classical fourth-order Runge-Kutta; the step is capped from the electrical time constant and natural frequency. Solenoid force uses `0.5 I² dL/dx` with a saturation cap; thermal-force and Brownian estimates use `sqrt(4 kB T b)` and `sqrt(kB T/k)`. | Bounded to 200,000 steps with a hard stroke clip. Coupling, `dL/dx`, Bl/torque constant, damping, spring, mass/inertia and limits are lumped inputs or reduced formulas. The model omits switching, controller dynamics, distributed modes, impacts/contact, position-dependent parasitics, detailed thermal flow and nonlinear field redistribution. Its core-loss power law is an empirical coefficient model; a zero coefficient means unknown, not zero loss. | [test_heater_magnetics.py](../tests/test_heater_magnetics.py) checks coupling, force/speed/resonance and friction cases. [test_winding_review.py](tests/test_winding_review.py) ensures an ordinary review does not run dynamics and that motion bounds remain explicit. These are numerical regressions, not actuator measurements. |
| Linear axisymmetric magnetostatic FEM | [axisymmetric.py](axisymmetric.py) solves first-order triangular `Aφ` elements on a feature-aligned `(r,z)` mesh with sparse NumPy/SciPy assembly. It recovers `Br = -∂Aφ/∂z` and `Bz = ∂Aφ/∂r + Aφ/r`, evaluates cylindrical curl energy with three-point triangle quadrature and returns `L = 2W/I²`, source work and residuals. A base mesh, doubled-cell mesh and 25%-larger air domain form the convergence report. | Annular windings, optional bore core and linear isotropic permeability only; `Aφ = 0` is imposed at a finite outer boundary. Dimensions are m, B is T, H is A/m, energy is J and L is H. No nonlinear B-H material, hysteresis, eddy currents, arbitrary 3-D/STEP geometry, conductor loss or Maxwell-stress force is implemented. Domain and mesh convergence remain model-specific acceptance checks. | [test_axisymmetric.py](tests/test_axisymmetric.py) checks an analytic finite-solenoid on-axis field, source/energy/residual consistency, sign and scaling, core response, convergence and invalid geometry. |
| Two-winding axisymmetric inductance extraction | [axisymmetric.py](axisymmetric.py) solves two unit-current load vectors on one mesh and forms `Lij = fiᵀ K⁻¹ fj`; it reports `M = L12`, `k = M/sqrt(L11 L22)` and short-circuit leakage `L11 - M²/L22` / `L22 - M²/L11`. Reciprocity, positive eigenvalues and magnetic energy are checked before export. | The windings must be non-overlapping annular regions in one linear magnetostatic domain. The result is a frozen small-signal matrix; it does not include frequency-dependent leakage, capacitance, winding loss, nonlinear cores or planar-PCB geometry inference. | [test_axisymmetric_coupled.py](tests/test_axisymmetric_coupled.py) checks reciprocity/energy, separation, overlap rejection, reflected impedance relationships and an independent Neumann-loop quadrature. That reference uses the NIST coaxial-loop formulation; it does not certify every mesh or boundary choice. |
| Electrostatic capacitance | [capacitance.py](capacitance.py) implements (1) a triangular axisymmetric scalar-potential solve for equipotential annuli in a homogeneous dielectric with an explicitly grounded enclosure, deriving the Maxwell capacitance matrix from terminal charges, and (2) a single-layer rectangular PCB sidewall integral weighted by squared local voltage difference under a linear voltage-versus-arc-length assumption. A separate adjacent-round-wire energy model is also available. | `εr` is explicit; lengths are m and results F. The FEM model is axisymmetric and homogeneous, not a 3-D winding extraction. The PCB result is only adjacent sidewall contribution: curved/multilayer windings are rejected and broad-face, substrate-interface, nonadjacent and fringe capacitances are omitted. The grounded enclosure changes the common-mode result, so enclosure sensitivity must be reviewed. | [test_capacitance.py](tests/test_capacitance.py) checks analytic coaxial capacitance, matrix symmetry/terminal mapping/energy, dielectric and geometry scaling, enclosure sensitivity, invalid geometries, round-wire energy and sidewall integration. |
| Passive equivalent circuits, reports and native SPICE execution | [equivalent.py](equivalent.py) builds explicit R-L-C, coupled-inductor, constant-Bl actuator and brushed-DC-motor subcircuits; enforces `|k| < 1`; maps mass/inertia to C, damping to `1/R` and spring to `1/L` in the force-current analogy; and requires reciprocal `Bl` or `Kt = Ke` in SI. It exports a project-local, board-hash-bound, non-overwriting evidence bundle. [simulation.py](simulation.py) runs the reviewed deck through the native [WayriCAD SPICE backend](../wayricad_runtime/spice_backend.py): 10 points/decade for electrical AC or a DC operating point for mechanical equivalents. | Rdc, incremental L, supplied/computed C, coupling and motor constants are frozen lumped values. Unknown capacitance/secondary resistance stays unknown instead of receiving a default. Native ngspice is an execution dependency, not evidence that the reduced model represents an arbitrary device. No frequency-dependent loss, distributed line, nonlinear saturation, motor commutation or automatic parameter extraction is added by simulation. | [test_equivalent.py](tests/test_equivalent.py) checks passivity, missing-data behavior, reciprocal mechanics, units, field/resistance separation, unique reports and Maxwell-to-SPICE energy equivalence. [test_simulation.py](tests/test_simulation.py) checks input rejection, AC sign/phase and a native RL reference. The project's recorded ngspice comparison is a numerical operating-point check, not measured validation. |
| Motor winding synthesis, logical layout, EMF/effort and mechanics | [motor_model.py](motor_model.py) assigns two-layer coil sides by a conventional star-of-slots phasor construction for 4–720 slots, even pole counts and 2–12 phases. Full-pitch/distributed, one-slot concentrated and chorded pitches are supported; signed coil-side sums produce winding factors for harmonics 1, 3, …, 13 and phase-balance metrics. The optional PM baseline is `Bplateau = Br lm/(lm + μr gap)` with fundamental `4/π Bplateau sin(π pole_arc/2)`. Sinusoidal phase linkage and its derivative produce EMF and ideal-current force/torque with an explicit power-equality check. [motor_layout.py](motor_layout.py) renders only the logical annular coil/phase assignment. Mechanics run either bounded RK4 ideal-current dynamics or a native-ngspice constant-effort equivalent. | Geometry in m, speed in m/s or rad/s, EMF in V, force in N and torque in N·m. Preview radii do not enter the equations. The winding assignment is not end-turn packing or PCB routing. The PM expression is a uniform-gap baseline. Models omit saliency, cogging, saturation, MMF/flux FEA, winding voltage/inverter/control dynamics, thermal loss, finite-stroke ends and manufacturing tolerances. Even-phase presets are independent H-bridge axes. | [test_motor_model.py](tests/test_motor_model.py) checks distributed/concentrated references, 2- and 5-phase balance, EMF/energy derivative/power consistency, phase events, PM/reverse/standstill cases, analytical mechanics and bounded ngspice output. [test_motor_layout.py](tests/test_motor_layout.py) checks logical layout and invalid dimensions. [test_winding_review.py](tests/test_winding_review.py) checks review boundaries. |

### Research, dependency and validation boundary

- The air-core current-sheet equation and its geometry coefficients are the one directly adopted literature method: S. S. Mohan, M. del Mar Hershenson, S. P. Boyd and T. H. Lee, [“Simple Accurate Expressions for Planar Spiral Inductances,”](https://doi.org/10.1109/4.792620) *IEEE Journal of Solid-State Circuits* 34(10), 1999. Its published geometry and accuracy range do not validate the plugin's resistance, capacitance, multilayer, core or actuator heuristics.
- The motor code cites §4.1 of S. M. Taghavi Araghi, A. Kiyoumarsi and B. Mirzaeian Dehkordi, [“Design, analysis and prototyping of a PM-assisted synchronous reluctance machine equipped with new-type of fractional-slot winding,”](https://doi.org/10.1049/elp2.70002) *IET Electric Power Applications* 19(1), 2025, as background for conventional star-of-slots winding-factor construction. The plugin does **not** implement or claim validation of that paper's novel shifted winding, PM-assisted reluctance machine or prototype.
- [NIST DLMF §19.34](https://dlmf.nist.gov/19.34) supplies the independent coaxial-circle mutual-inductance reference used by the coupled-field test. The [Ansys Maxwell capacitance-matrix definition](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v242/en/Subsystems/Maxwell/Content/CapacitanceinTermsofChargesandVoltages.htm) and [FEMM electrostatics tutorial](https://www.femm.info/doku/doku.php?id=electrostaticstutorial) are comparison/background references for matrix signs, energy and finite-boundary sensitivity. None is a runtime dependency or third-party certification of this solver.
- KiCad's bundled ngspice is invoked through the shared backend; the [official ngspice documentation](https://ngspice.sourceforge.io/docs.html) describes that simulator. Passing a SPICE regression validates deck construction and numerical execution only. All other packing rules, AC multipliers, reduced core-loss/force models and logical-layout choices described above are project-specific analytical or numerical methods, with no research pedigree implied.

The tracked planar test files are linked from the corresponding table rows above and are supplemented by the integration cases in [tests/test_heater_magnetics.py](../tests/test_heater_magnetics.py). They exercise equations, invariants, rejection paths and recorded numerical references. They do not establish measured core loss, fringing, distributed saturation, EMI, winding tolerance, insulation/breakdown, mechanical strength, thermal qualification or production motor/actuator performance.
