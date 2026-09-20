# Magnetics model verification

The two-winding extractor solves linear axisymmetric magnetostatics for two non-overlapping coaxial annular winding volumes and an optional linear core. It is separate from the generated PCB-winding approximation. Results are numerical models, not measurements or arbitrary STEP analysis.

## Coupled energy model

Two unit-current excitations use the same feature-aligned mesh and stiffness matrix. If `f1` and `f2` are their load vectors, the extracted matrix is `Lij = fiᵀ K⁻¹ fj`. The solver checks residuals, reciprocity, energy consistency and positive eigenvalues before returning a result. Coupling is `k = M / sqrt(L11 L22)`. The short-circuit equivalent leakage is `L11 − M²/L22` at the primary and `L22 − M²/L11` at the secondary; it is not a separately identified spatial leakage region.

Tests cover turn-count scaling, current independence of linear inductance, separation trends, axial reflection, overlapping geometry, invalid values and energy/passivity. Neither reciprocity nor a small algebraic residual alone proves mesh accuracy.

## Independent air-core reference

For coaxial circular filaments with radii `a`, `b` and axial separation `h`, define `m = 4ab / ((a+b)²+h²)`. In SI units:

```text
Mloop = μ0 sqrt(ab) [(2−m) K(m) − 2 E(m)] / sqrt(m)
```

Here `K` and `E` use the elliptic **parameter** `m`, as in SciPy, rather than modulus `sqrt(m)`. This is the Maxwell/Neumann circular-filament reference. See [NIST DLMF §19.34](https://dlmf.nist.gov/19.34) for the underlying coaxial-circle integral (its displayed units are cgs); the expression above uses SI permeability and metres.

The test averages filament mutual inductance over both uniform rectangular winding cross-sections with independent Gauss–Legendre quadrature. Both windings have radii 8–10 mm and height 6 mm; their centres are 9 mm apart. Turns are 20 and 30. There is no core. The FEM air multiplier is 8, with fixed geometry during mesh refinement.

| Calculation | Mutual inductance |
|---|---:|
| 5-point quadrature per integration dimension | 2.9340697107 µH |
| 8-point quadrature | 2.9340698509 µH |
| 12-point quadrature | 2.9340698509 µH |
| FEM 64 radial × 128 axial base cells | 2.9532817792 µH |
| FEM 128 radial × 256 axial base cells | 2.9307429897 µH |

Relative to the 12-point reference, FEM error decreases from **0.6548% to 0.1134%**. The automated test requires the finer error below 0.5% and below the coarser error. Inserted feature boundaries increase actual mesh counts beyond the base grid. [Recorded matrices, coupling and conservation evidence](audits/MAGNETICS_COUPLED_REFERENCE.json).

The finite outer boundary enforces zero vector potential. Mesh and air-domain sensitivity must be checked separately: a smaller air box showed cancellation between discretization and truncation errors, so monotonic error reduction is not assumed for every configuration. This air-core benchmark does not validate nonlinear materials, hysteresis, saturation, eddy currents, AC leakage, electrostatic capacitance or imported solids.

## Equivalent-circuit boundaries

The reduced generated-winding model can report operating-point B/H, declared effective magnetic path, core/gap reluctance and incremental inductance. Those closed-core quantities are not assigned to an open air winding without a defined effective path. Field-derived B/H and mutual inductance belong to the explicitly entered coaxial geometry.

SPICE exports retain model assumptions and missing parasitics. Capacitances can be supplied or computed with the separate electrostatic/sidewall models below. The coaxial magnetic model still requires explicit winding resistance; omitted values remain unknown. Mechanical equivalents use supplied reciprocal transduction constants and lumped mechanical parameters, not a solved rotating machine. Use the companion JSON/HTML together with the subcircuit.

Run the numerical tests in the prepared scientific runtime:

```console
python -m unittest discover -s planar_magnetics_plugin/tests -p "test_axisymmetric*.py" -v
```

## KiCad bundled SPICE reference checks

The exported models were executed against **ngspice 46 bundled with KiCad 10**, in an isolated process. Nine checks across four circuits passed against independent circuit equations:

| Circuit | Reference and result |
|---|---|
| Inductor DC | 12 V / 2 ohms = 6 A |
| Loaded coupled transformer, 1 kHz | Complex input current and load voltage match independent coupled-inductance equations within 3e-16 relative error |
| Linear actuator | 1 A current, 4 m/s velocity, 8 W converted mechanical power |
| Rotary motor | 1 A current, 4 rad/s angular velocity, 8 W converted mechanical power |

[Recorded actual and expected vectors](audits/MAGNETICS_SPICE_REFERENCE.json). These checks establish circuit implementation and sign conventions for the specified parameters. They do not establish the accuracy of a physical motor, winding capacitance, core loss or nonlinear material model.

## Electrostatic capacitance references

The interwinding solver uses the axisymmetric scalar-potential weak form with explicit, homogeneous relative permittivity. Each annular conductor is equipotential. Two unit-voltage solutions provide the Maxwell matrix `Q = C V`; stored energy is `Vᵀ C V / 2`. The interconductor branch is `-C12`, and the two row sums are separate capacitances to the specified outer reference. Matrix reciprocity, positive eigenvalues, residuals and energy agreement are checked. This distinction follows the [ANSYS capacitance-matrix formulation](https://ansyshelp.ansys.com/public/Views/Secured/corp/v251/en/ans_thry/thy_emg10.html). [FEMM's electrostatics tutorial](https://www.femm.info/doku/doku.php?id=electrostaticstutorial) provides an independent reference for prescribed conductor potentials and charge/voltage extraction. Neither external solver was executed for these checks.

The analytical coaxial reference uses inner electrode outer radius 1 mm, outer electrode inner radius 2 mm, length 10 mm and relative permittivity 3. Insulated axial ends make the solution uniform along its axis. `C = 2π ε length / ln(b/a)` gives **2.407822075859 pF**. The same production FEM produces relative errors **0.12910%, 0.03636%, 0.00940%** at 16, 32 and 64 base radial cells.

A separate finite-height pair checks enclosure sensitivity while preserving local base spacing: winding radii 2–3 and 4–5 mm, heights 4 mm, relative permittivity 2. Enclosure radius/half-height 10, 20 and 30 mm produce mutual branches **2.009450, 2.062458 and 2.075813 pF**. Radial/axial cell counts grow proportionally with the enclosure. This is sensitivity evidence, not a universal open-boundary convergence certificate. Environment branches remain in the result. [Recorded matrices and numerical evidence](audits/MAGNETICS_CAPACITANCE_REFERENCE.json).

The generated single-layer rectangular PCB model computes **only adjacent sidewall coupling** from actual parallel-segment overlap, copper thickness and gap. It integrates the squared voltage difference under an explicit linear conductor-arc-length potential assumption. A U-shaped reference verifies the energy reduction analytically. Fringing, broad-face, interlayer and surrounding-conductor effects are absent, so the value is a partial contribution, not a full winding capacitance or validated self-resonance prediction. A separate adjacent round-wire approximation states its geometry and voltage assumptions; it is not silently applied to rectangular PCB traces.

Applying an equipotential whole-winding capacitance matrix to differential transformer terminals requires an explicit terminal/reference approximation. It is not interchangeable with a turn-distributed intrawinding model. Retain the geometry, reference-boundary and terminal-mapping assumptions alongside any SPICE export.
