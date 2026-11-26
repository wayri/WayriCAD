# Parallel-Plate PDN Cavity Ports

`plane_ports.py` is a standalone 2D triangular finite-element **quasi-TEM
parallel-plate cavity** solver. Unlike the separate MQS conductor-section
solver, it includes distributed dielectric capacitance and in-plane wave
resonances. It is not a Palace integration, a full-wave solver, or automatic
board extraction. No Palace accuracy or performance comparison has been run.

## API And Integration

```python
from quick_pi_plugin.plane_ports import run_study, validate_study
result = run_study(study, cancel=event)  # cancel is optional
```

`run_study` returns finite JSON-compatible evidence; `validate_study` returns
a normalized study dictionary. Malformed/unsupported input raises `ValueError`;
numerical invariant failures raise `RuntimeError`. A set cancellation event
raises `concurrent.futures.CancelledError`. Cancellation checkpoints are before
validation/assembly and between frequency solves, not inside a factorization.
No wx, matplotlib, NumPy or SciPy is imported merely by importing this module.
NumPy/SciPy are loaded when validation/solving is requested.

In Quick PI, choose one net and assign two pad groups using Source pad and Load
pad, then **More > Planar PDN impedance from selected pad ports**. The existing
saved-copper mesher supplies the geometry. Both contacts become positive ports
relative to the declared common ideal reference plane, not a differential pair
or a DC termination. Enter the assumed separation/material properties and
explicitly confirm the full ideal plane and magnetic-wall boundary model.
The adapter rejects multilayer, via-containing, noncoplanar and nonuniform-
thickness meshes; the solver rejects disconnected or overlapping port groups.
Reference-plane coverage is an assumption, not an automatic void/return audit.
Fringing on narrow traces is not modelled; parallel-plate accuracy is not
established where conductor widths are comparable with dielectric separation.

```text
wayricad-pi --plane-ports study.json --output impedance.json --timeout 300
```

The CLI accepts a bounded explicit mesh JSON and returns 3 for `MODELLED`
evidence without demonstrated mesh convergence, or 2 for invalid/failed/cancelled
work. Both UI and CLI retain model assumptions and original complex samples.
The native result window provides log-log magnitudes, actual-reference overlays,
common-sample dB differences, pan/zoom and hover probes. See the
[comparison format](AC_PORTS.md#magnitude-and-reference-plots).

## Exact Input Contract

Top-level fields are exactly those shown below, with `temperature_c` optional
(default 20). All other fields are required. This coarse example illustrates
the **schema only**, not a GHz- or resonance-qualified mesh:

```json
{
  "schema": "wayricad.pi-plane-ports/v1",
  "reference_plane": "ideal",
  "vertices_mm": [[0, 0], [100, 0], [100, 50], [0, 50]],
  "triangles": [[0, 1, 2], [0, 2, 3]],
  "dielectric_height_mm": 0.2,
  "epsr": 4.0,
  "tandelta": 0.01,
  "copper_thickness_mm": 0.035,
  "resistivity_ohm_m": 1.7241e-8,
  "temperature_c": 20,
  "ports": [
    {"name": "P1", "nodes": [0, 3], "weights": [0.5, 0.5]},
    {"name": "P2", "nodes": [1, 2], "weights": [0.5, 0.5]}
  ],
  "frequencies_hz": [100000, 100000000]
}
```

| Field | Meaning And Bounds |
| --- | --- |
| `vertices_mm` | List of 3-50000 unique `[x,y]` points in mm; coordinates finite, magnitude <= 1e6 mm. |
| `triangles` | List of 1-100000 three-index elements. Zero-based integer indices; either orientation. |
| `reference_plane` | Must be the literal `"ideal"`; a common equipotential plane outside the nodal unknowns. |
| `dielectric_height_mm` | Uniform normal separation, 1e-6 to 100 mm. |
| `epsr` | Uniform frequency-independent relative permittivity, 1 to 100. |
| `tandelta` | Uniform dielectric loss tangent, 0 to 1. |
| `copper_thickness_mm` | Uniform thickness of the one resistive sheet, 1e-6 to 10 mm. |
| `resistivity_ohm_m` | Resistivity at 20 degC, 1e-12 to 1e-4 ohm m. Copper temperature coefficient is fixed. |
| `temperature_c` | Optional fixed uniform temperature, -40 to 200 degC, default 20. No thermal solve. |
| `ports` | Exactly two objects with exactly `name`, `nodes`, `weights`. |
| `frequencies_hz` | List of 1-512 distinct finite numbers in [1e4,1e10] Hz; sorted on normalization. No DC. |

Numbers must be JSON numbers, not strings or booleans. Port names must be
unique nonempty strings of at most 80 characters. Each port's nodes and weights
are equal-length nonempty lists. Every node index is valid and appears only
once within or across both ports. Weights must be strictly positive and sum
to 1 within absolute tolerance 1e-12; only accepted roundoff is normalized
away. Unknown fields are rejected. There is no negative-node group: the
negative terminal is explicitly the common ideal plane for both ports.

Every mesh vertex must be used. Triangle indices must be distinct and elements
must not duplicate an existing element in any ordering. Triangle absolute area
must be at least 1e-24 m2, with twice-area greater than 1e-12 times its longest
squared edge. Degenerate elements, edges incident to more than two triangles,
and neighboring elements on the same side of their shared edge are rejected.
The mesh must be one edge-connected domain; even islands touching at a lone
vertex are rejected. Holes are permitted and their edges are magnetic walls.
The provider must supply a conforming, non-self-intersecting mesh: these
bounded topology/local geometry checks do **not** certify global absence of
crossing elements, T-junctions or self-intersections.

The highest supplied frequency must satisfy
`height_m * f * sqrt(mu0*eps0*epsr) < 0.1`, i.e. separation less than one tenth
of the in-dielectric wavelength. This excludes use near the first higher
transverse parallel-plate mode; it does not certify that the in-plane mesh is
resolved. Lateral electrical size is not restricted to the MQS small-size limit.

## Spatial Equations And Boundaries

The unknown is plane-to-reference voltage `V(x,y)` over the explicit triangle
domain. Piecewise-linear nodal shape functions `Ni` give:

```text
Kij = integral(grad(Ni) dot grad(Nj)) dA
c_i += eps0 * epsr / height_m * triangle_area_m2 / 3
Cmass = diag(c_i)

rho(T) = resistivity_ohm_m * (1 + 0.00393*(temperature_c - 20))
Rs(f) = max(rho(T)/thickness_m, sqrt(pi*f*mu0*rho(T)))
Zsheet = Rs + j*omega*mu0*height_m
Y = K/Zsheet + j*omega*Cmass + omega*Cmass*tandelta
Y @ V = B
Z = B.T @ V
```

`K` is dimensionless and `Cmass` is in farads. Each `B` column places positive
unit-current weights at one port's nodes and zero elsewhere. Column 1 excites
`I1=1 A RMS, I2=0`; column 2 excites `I1=0, I2=1 A RMS`. Voltages are weighted
with the same B columns to preserve power conjugacy. Port groups are not
artificial equipotential contacts. `Zij` observes voltage at i due to current
at j, with the other port current zero. Phasors use `exp(+j*omega*t)`.

Magnetic walls impose homogeneous natural Neumann conditions on **every**
boundary. There is no pinned node, boundary resistor, arbitrary ground sink,
absorbing wall or edge radiation. The ideal reference accepts the total return
current: for either unit drive the integral dielectric displacement plus loss
current is +1 A, hence reference-plane current is -1 A. Both ports are positive
terminals, not a balanced source/sink pair within the signal sheet.

There is only **one** resistive sheet. The reference plane has zero ohmic loss;
no second Rs is added. `mu0*h` is the external sheet inductance. The real Rs
envelope is an explicitly approximate DC/skin model with a crossover kink,
not an exact finite-thickness impedance or proven upper error bound. It omits
internal inductance, skin-effect reactance, surface roughness and frequency
dispersion. No internal inductance is added twice.

### Stable Uniform Mode

`K @ 1 = 0`. The uniform capacitor voltage can dominate the spatial voltage
differences at low frequency, making a direct nodal solve lose digits. With
`Ct=sum(c)`, this implementation separates the exact uniform mode:

```text
V0 = 1 / (omega*(tandelta+j)*Ct)
V = W + 1*V0
[Y, c] [W     ] = [B - c[:,None]/Ct]
[c.T,0] [lambda]   [0               ]
```

This is a sparse (N+1)-unknown system with two RHS columns and one factorization
per frequency. The constraint `c.T@W=0` fixes only this algebraic decomposition,
not a physical voltage node. It is equivalent to `Y@V=B`; RF tests compare it
against direct Y solves. Residuals are evaluated as `Y@W-(B-c/Ct)` to avoid
spurious floating-point leakage from `K@1`. The conductor-loss quadratic form
likewise uses W rather than subtracting large uniform voltages.

## Output And Checks

The result envelope has `schema: "wayricad.pi-plane-ports/v1"`, `kind: "result"`,
`status: "MODELLED"`, normalized `study`, `boundary: "magnetic-walls-neumann"`,
`reference_plane: "ideal"`, `model`, `phasor_convention`, and `units` including
`frequency: "Hz"`, `impedance: "ohm"`, `input_geometry: "mm"`, `current: "A"`.
`area_m2`, `total_capacitance_f`, and
`resistivity_at_temperature_ohm_m` preserve explicit physical units.

`frequencies` is a list of rows compatible with the AC port plotting convention:

```text
frequency_hz
z_ohm = [[Z11, Z12], [Z21, Z22]]
checks = {residual_relative_error, current_relative_error,
          net_current_error_a, reciprocity_relative_error,
          hermitian_min_eigenvalue_ohm, power_relative_error}
sheet_resistance_ohm_per_square
reference_plane_current_a = [return_for_drive_1, return_for_drive_2]
```

Every complex value is `{"real": number, "imag": number}`; no magnitude-only
replacement, stringified complex values, or implicit display-unit conversion.
For low frequency all four entries approach the negative-imaginary common
capacitor impedance `1/(omega*(tandelta+j)*Ct)`. Spatial modes produce cavity
resonances and signed reactive changes at RF.

Every frequency must pass relative RHS residual, integrated total return
current, reciprocity `norm(Z-Z.T)/norm(Z)`, and full matrix power balance within
1e-7. The latter compares `H=(Z+Z.conj().T)/2` against the copper and dielectric
loss quadratic forms, relative to their matrix norm. Passivity checks
`min(eigvalsh(H)) >= -1e-9*norm(Z)` for roundoff. These invariants reject
nonphysical/failed numerical solutions; they do not validate model omissions.
Results are not symmetrized or made positive after solving. Strict JSON export
rejects nonfinite output.

`work` reports one assembly and the actual completed frequency count for both
`factorizations` and `multi_rhs_solves`, with `rhs_columns_per_solve: 2`.
Matrix geometry and capacitance are reused only inside a call; there is no
global cache. Frequency factors are discarded after each solve. Limits are
50k vertices, 100k triangles and 512 frequencies, not a guaranteed worst-case
memory or runtime bound for arbitrary fill-in. Sparse solves are in-memory;
there are no installations, downloads, generated mesh files or external solvers.

`convergence.status` is always `"NOT_EVALUATED"`; there is no automatic mesh or
frequency refinement and no `CONVERGED` verdict. Refine the mesh while keeping
port contact geometry/weights physically equivalent, then refine frequency
sampling near peaks. Point ports, lumped capacitance, under-resolved meshes,
narrow peaks and approximated sheet reactance can shift resonance magnitude
and frequency. No radiation, launches, vias, stacks, component models or
unmodeled return geometry are implied. Limitations and primary references are
included in each result.

The separate [real-board Marble Zxx demonstration](examples/marble_zxx/README.md)
includes a saved trace mesh, the complex impedance sweep and CLI replay steps.

## Focused Validation

```text
python -B -m unittest discover -s tests -p test_plane_ports.py -v
```

Synthetic uniform-grid generation exists only in the tests. Checks cover the
low-frequency total capacitance, unit/ideal-return conservation, Neumann null
mode, geometry scaling in mm, reciprocity, Hermitian passivity and loss balance,
triangle orientation, rigid rotation/translation, port permutation, one real
LU/two-RHS call per frequency, RF direct-Y equivalence, temperature/loss model,
cancellation, headless imports, malformed ports/frequencies and invalid topology.

Windows local check: 14 tests passed with generic Python 3.11, NumPy 2.2.6,
SciPy 1.17.1 using existing dependencies and `-B`. For the 100 x 50 mm rectangle,
epsr=4, h=0.2 mm, 24 x 12 test grid (325 nodes/576 triangles), the analytical
first mode is `f10=1/(2*L*sqrt(mu0*eps0*epsr)) = 749.481145 MHz`. An 81-point
lossy scan sampled a Z11 magnitude peak at 748.356923 MHz (-0.15%), about
29.815 ohm; maximum residual was 7.01e-13. This is a synthetic analytical
frequency-reference check, not a physical or Palace comparison and not a
general mesh-accuracy guarantee. Full repository, packaging, board-adapter and
UI validation are outside this module's verification scope.

## Primary References

- [MIT Electromagnetics and Applications, chapter 9](https://ocw.mit.edu/courses/6-013-electromagnetics-and-applications-spring-2009/MIT6_013S09_chap09.pdf):
  waveguides, standing waves and cavity resonators. The rectangular Neumann
  scalar model here has lateral eigenvalues `(m*pi/L)^2+(n*pi/W)^2`;
  substituting into the stated wave equation gives the analytical test above.
- [COMSOL TEM/quasi-TEM modeling](https://www.comsol.com/support/learning-center/article/modeling-tem-and-quasi-tem-transmission-lines-21971):
  parallel-plate TEM assumptions, conductor-loss approximations and reflecting
  magnetic walls as distinct from radiation boundaries.
- [SciPy SuperLU.solve](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.SuperLU.solve.html):
  factored sparse systems accept multiple RHS columns.

These references motivate the model and numerical technique; they do not
validate this implementation or establish equivalence to another solver.
