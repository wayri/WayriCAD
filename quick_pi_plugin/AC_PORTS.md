# Explicit Two-Port AC Impedance

This module extracts the impedance matrix of **explicit straight parallel
rectangular copper conductors**, using the existing Quick PI 2D
magnetoquasistatic (MQS) cross-section discretization. It does not extract a board,
integrate Palace, or replace a full-wave field solver. No speed comparison with
Palace has been performed.

## Entry Points

Headless API:

```python
from quick_pi_plugin.ac_ports import run_study
result = run_study(study)
```

The result is a finite JSON-compatible dictionary. Input errors raise
`ValueError`; failed numerical invariants raise `RuntimeError`. An optional
keyword `cancel=threading.Event()` raises `concurrent.futures.CancelledError`
when set. Cancellation is checked between mesh/frequency solves, not inside
SuperLU. There is no global mesh or factorization cache.

Standalone UI: `python -B -m quick_pi_plugin.ac_ports_ui`. An integrating caller
can use `create_frame(parent=None, study=None)` (does not show the frame) or
`launch(parent=None, study=None)` (uses an existing wx application if present).
The module imports wx, matplotlib and the existing Quick PI plotting adapter
only when the frame is created. Headless module imports do not load those
dependencies or NumPy/SciPy. The UI has editable geometry, terminal choices,
frequency inputs, a table of all eight real/imaginary impedance components,
and signed real/imaginary curves for all four matrix entries. Inputs invalidate
results and exports. Load accepts study JSON; Save Result includes the complete
normalized study. The UI never reads or writes PCB geometry.

From Quick PI, use **More > AC two-port impedance**. For headless workflows:

```text
wayricad-pi --ac-ports study.json --output impedance.json --timeout 300
```

The CLI bounds input to 4 MiB, rejects duplicate JSON keys and nonfinite values,
protects the input from output aliases and checks its saved-byte hash again at
publication. Exit 0 means numerical convergence, 3 means provisional results,
and 2 means rejected input or a failed/cancelled solve. Timeout/cancellation is
cooperative between sparse solves, not an interrupt inside a factorization.

The inputs are explicit conductor geometry and port returns. Selecting a PCB
net does not silently supply missing return paths, uniform cross-sections or
mutual inductance for bends, vias and zones.

## Exact Study Contract

### Magnitude And Reference Plots

The result view uses one log-log magnitude panel per Z11/Z12/Z21/Z22 term with
Hz/ohm scales, pan/zoom controls and nearest-original-sample hover probes showing
real/imaginary impedance and phase. Exact zero magnitudes are omitted from log
curves, not replaced with an arbitrary floor; original values remain in JSON.

**Reference...** accepts a UTF-8 JSON file up to 4 MiB with schema
`wayricad.impedance-reference/v1`, `units: {"frequency":"Hz","impedance":"ohm"}`
and `frequencies` rows in the same `frequency_hz` / 2-by-2 `z_ohm` format as
solver results. Each complex entry is `{ "real": 1, "imag": -2 }` in ohms.
Frequencies must be finite, positive and strictly increasing. All four terms
must be supplied; reciprocity is not invented to fill missing data.

The lower panels show `20 log10(|Zmodel| / |Zreference|)` only at common nonzero
sample frequencies (relative matching tolerance 1e-9). No interpolation or
extrapolation is used. A filename label is not evidence that the data came from
Palace. Generate/convert actual reference results and match geometry, material,
ports and boundaries before drawing accuracy conclusions. Save Result retains
the complete imported reference dataset and its comparison basis.

For distributed plane capacitance and resonances, use the separate
[planar PDN cavity model](PLANE_PORTS.md), not the MQS section below.

The top-level object has exactly four fields. Example (all dimensions in mm):

```json
{
  "schema": "wayricad.pi-ac-ports/v1",
  "cross_section": {
    "length_mm": 10,
    "temperature_c": 20,
    "relative_permittivity": 4.2,
    "mesh_step_mm": 0.1,
    "air_padding_mm": 1,
    "max_cells": 20000,
    "convergence_tolerance": 0.05,
    "conductors": [
      {"name": "A", "x_mm": -0.4, "y_mm": 0.2, "width_mm": 0.4, "thickness_mm": 0.1},
      {"name": "B", "x_mm": -0.4, "y_mm": -0.2, "width_mm": 0.4, "thickness_mm": 0.1},
      {"name": "C", "x_mm": 0.4, "y_mm": 0.2, "width_mm": 0.4, "thickness_mm": 0.1},
      {"name": "D", "x_mm": 0.4, "y_mm": -0.2, "width_mm": 0.4, "thickness_mm": 0.1}
    ]
  },
  "ports": [
    {"name": "P1", "positive": "A", "negative": "B"},
    {"name": "P2", "positive": "C", "negative": "D"}
  ],
  "frequencies_hz": [100, 1000, 10000]
}
```

- `cross_section` permits only the fields shown. `length_mm` and `conductors`
  are required. Each conductor has exactly the five shown fields. Coordinates
  are centers; width is along x and thickness along y. Conductors must not
  overlap or touch. Names are unique, nonempty strings of at most 80 characters.
  There are 2-16 conductors; two independent loops actually require at least
  three conductors. Extra passive conductors have zero prescribed net current.
- `ports` contains exactly two objects with exactly `name`, `positive`,
  `negative`. Port names are distinct nonempty strings of at most 80 characters.
  Terminals must name distinct existing conductors. Shared return conductors
  are allowed. Duplicate loops and polarity-reversed duplicate loops are not
  independent and are rejected. No return is inferred.
- `frequencies_hz` is a list of 1-32 distinct finite numbers, each at least
  `1e-6` Hz. Booleans, DC, duplicates and nonfinite values are rejected.
  Normalization sorts frequencies ascending without changing port order.
- Existing cross-section validator defaults apply: temperature 20 degC
  (-40 to 200), relative permittivity 4.2 (1 to 100), mesh step 0.05 mm
  (`1e-6` to 1000), air padding 1 mm (`1e-5` to 10000), `max_cells` 60000
  (integer 100 to 100000), convergence tolerance 0.05 (0.001 to 0.2).
  Length is `1e-6` to `1e6` mm. Width/thickness are positive and at most
  `1e4` mm; center-coordinate magnitude is at most `1e6` mm.
- `current_scale`, `harmonics`, waveform and DC drive fields are intentionally
  absent: port columns alone define the excitation. They are not silently
  ignored. Unknown fields are rejected.

The existing AC study validator is called after assigning the first explicit
port loop and unit harmonic currents. It checks all conductor dimensions and
all frequencies, including the electrical-size guard:

`2*pi*f*max(length, cross-section diagonal)*sqrt(relative_permittivity)/c <= 0.1 rad`

Dimensions in this formula are meters. Permittivity is only a validity guard;
it does not introduce capacitance into the MQS equations.

## Equations And Port Convention

Let `B` be the conductor-by-port incidence matrix: each column has +1 at its
positive conductor and -1 at its negative conductor, zero elsewhere. Both
columns are balanced and linearly independent. For each frequency solve the
same assembled field equations as `ac_analysis._frequency`:

```text
[K + j*w*mu0*S, -j*w*mu0*C] [u] = [0]
[-C.T,                    G] [E]   [B]

u = j*w*A
J = (E[conductor] - u[cell]) / rho
Z = B.T @ E * length_m
rho = 1.7241e-8 * (1 + 0.00393*(temperature_c - 20)) ohm m
```

The solution has two columns. Column 1 imposes `I1=1 A RMS, I2=0`; column 2
imposes `I1=0, I2=1 A RMS`. Thus `Zij=Vi/Ij` with the other **port current**
zero. Local eddy currents need not vanish in an unexcited conductor. With
shared conductors, their prescribed currents are the sum of loop contributions.
`Vi` is the positive-minus-negative axial voltage over the specified length;
phasors use `exp(+j*w*t)`. Rows observe ports, columns excite ports. Flipping
one port multiplies both its row and column by -1, leaving self impedances
unchanged. `B.T` is an ordinary transpose (B is real).

`dc_resistance_ohm = B.T @ diag(rho*length_m/area_m2) @ B` is an analytical
DC reference matrix, not a separate lumped approximation used in the AC solve.
The AC solution includes skin and proximity redistribution within its supported
geometry. Self impedance includes both explicit outgoing and return paths.

## Bounds, Work And Numerical Evidence

One `scipy.sparse.linalg.splu` factorization and one `.solve(rhs)` call with two
RHS columns occur per frequency **per mesh**. This avoids two independent
factorizations for the two drives; it establishes no runtime ratio or Palace
speedup. All-frequency results from the current mesh are reused in boundary
comparisons, then discarded when no longer needed. There is no cross-study
cache, installation or subprocess solver.

The existing mesh generator resolves copper faces exactly and adapts to the
highest-frequency skin depth. It enforces a per-mesh cell budget. The sequence
is fine mesh (refinement 0.5), up to four successive air-padding doublings, and
coarse mesh (refinement 1.0) at the final boundary. This is 3-6 meshes, hence
at most 192 factorizations for 32 frequencies, not two per port. Meshes are
assembled sequentially; oversized meshes fail, rather than returning a
nominally converged fallback.

At every solved frequency, the implementation checks:

- Integrated conductor currents against both B columns and total current
  conservation (unit-current relative/absolute tolerance `1e-7`).
- Reciprocity `norm(Z-Z.T)/norm(Z) <= 1e-7`, without symmetrizing the result.
- Positive semidefiniteness of `H=(Z+Z.conj().T)/2`, allowing only eigenvalue
  roundoff down to `-1e-10*norm(Z)` ohm.
- Full matrix Joule balance `H = rho*length*J.conj().T@diag(cell_area)@J`
  within `1e-7` relative Frobenius norm. This covers arbitrary complex port
  combinations, not only two individually positive diagonal resistances.

Fine/coarse and successive boundary matrix differences use the maximum of
entrywise complex errors scaled by `sqrt(abs(Zii)*abs(Zjj))` and relative
Frobenius error in the real matrix. Scaling transfers by self impedances avoids
division by a symmetry-zero mutual term; it does not establish relative
accuracy of an arbitrarily small mutual entry. No field-map convergence claim
is made. All frequencies must satisfy both comparisons at the configured
tolerance for `CONVERGED`; otherwise the result is explicitly `PROVISIONAL`.
`CONVERGED` is numerical sensitivity evidence, not physical qualification.

## Result Envelope

The result uses schema `wayricad.pi-ac-ports/v1`, `kind: "result"`, normalized
`study`, `status`, model description, units, phasor convention, resistivity,
analytical `dc_resistance_ohm`, and `frequencies`. Every frequency row contains:

```text
frequency_hz
z_ohm = [[Z11, Z12], [Z21, Z22]]
checks = {current_relative_error, net_current_error_a,
          reciprocity_relative_error, power_relative_error,
          hermitian_min_eigenvalue_ohm,
          mesh_relative_error, boundary_relative_error}
```

Each impedance is `{"real": number, "imag": number}`, in **ohms**, without
stringifying complex values or converting stored results to display units.
The envelope also records `mesh` (cell counts, final padding, boundary history),
`work` (measured factorization/solve/mesh counts), `convergence` (tolerance and
scope), `limitations` and `references`. Geometry in the normalized study stays
in mm. Strict JSON serialization rejects nonfinite output.

## UI Lifecycle

One worker serializes solves; at most one latest pending study is retained.
Submitting newer input cancels the active generation cooperatively and replaces
the pending request. Editing/cancelling invalidates queued callbacks as well as
the active run. Close invalidates the generation and prevents UI delivery;
an active noninterruptible sparse solve may finish in the daemon worker.
Every UI delivery is queued through `wx.CallAfter` and rechecks generation and
closed state on the UI thread. Worker errors do not leave a previous result
exportable. The native minimum window has scrollable inputs and a persistent
command row; results have a horizontally scrollable numerical grid.

## Verification And Limitations

Focused tests: `python -B -m unittest discover -s tests -p test_ac_ports.py -v`.
Optional native tests: same command with `test_ac_ports_ui.py`, using the
existing KiCad wx runtime. Checks cover DC resistance, symmetry, reciprocity,
port reversal, shared-return coupling, scalar-backend equivalence, JSON units,
input rejection, electrical size, budgets, provisional output, actual LU/RHS
counts, lazy imports, cancellation, latest/closed delivery guards, and native
minimum sizing and complete result table/curves.

Local verification on Windows (2026-11-15): 13 focused headless tests passed
with generic Python 3.11, NumPy 2.2.6 and SciPy 1.17.1; three native tests passed
with KiCad's Python 3.11.5, wxPython 4.2.2, NumPy 2.4.2, SciPy 1.17.1 and
matplotlib 3.10.8. Native tests used the repository's existing plotting fallback
because this KiCad installation lacks `wx.svg._nanosvg`. The example above
returned `CONVERGED`: three meshes, nine factorizations, nine two-column solves,
maximum mesh error 0.001132 and maximum boundary error 0.000897. These are
example-specific numerical checks, not a benchmark. The full repository matrix,
packaging, editor-connected operation and screenshot review were not performed.

This implementation has no capacitance, dielectric loss, displacement current,
radiation, magnetic material, bend, via, zone, full-board mesh, automatic return
inference, nonlinear device model or thermal coupling. It is not a generic
lumped model labelled as board extraction. It does not establish insulation,
ampacity, regulatory compliance, measurement agreement or Palace equivalence.
Independent field-solver and measured-hardware validation remain future work.

## Primary References

- [FEMM 4.2 manual, sections 1.2.2 and 2.2.7](https://www.femm.info/Archives/doc/manual42.pdf):
  time-harmonic magnetic vector potential, conductive currents and circuit
  constraints. FEMM is a formulation reference, not the solver used here;
  this module uses the repository's finite-volume equations.
- [SciPy SuperLU.solve](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.linalg.SuperLU.solve.html):
  one factorization object accepts a matrix of right-hand sides.
- [NBS Copper Wire Tables](https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf):
  copper resistivity/temperature reference inherited from `ac_analysis`.

These sources describe formulations and material data, not validation of this
implementation or a performance benchmark. The inherited backend's references
and limitations are also included in every result.
