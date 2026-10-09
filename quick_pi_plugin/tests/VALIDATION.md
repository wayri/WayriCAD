# Quick PI numerical validation

Run the tests from the repository root using KiCad's Python runtime:

```powershell
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m unittest discover -s quick_pi_plugin/tests
```

The solver tests compare copper-strip resistance, voltage, current density and
Joule power against analytical equations. They cover parallel layers, barrel
resistance, positive and ideal series RL branches, fixed forward drops and
anchored diode DC operating points, disconnected copper, current
and energy conservation, winding reversal, nonuniform contact-current spreading
under mesh refinement, and ill-conditioned equipotential slivers. Ideal-inductor
loops report indeterminate individual currents rather than inventing them.

## Multiple sinks and source capacity

Each sink is an independent ideal electrode with a positive, constant current
demand `I_i` in amperes. The source fixes voltage `V_s` in volts. Kirchhoff
balance requires `I_source = sum(I_i)` and conductor/component Joule loss must
match `sum(I_i * (V_s - V_i))` in watts. The solver retains the existing
1e-6 relative current/nodal and energy acceptance thresholds.

`test_multisink_solver.py` independently compares separate branches and a shared
trunk against `R = rho * length / area`, branch `I * R` drops, and `I^2 * R`
losses. Shared-trunk current is the sum of sink demands; each ideal series
inductor's tree current and stored energy are checked separately. Tests cover
load order, legacy equivalence, separate voltage windows, overlapping contacts,
disconnected sinks, malformed inputs, and source demand below/at/above capacity.
The source-budget boundary permits only 1e-12 relative floating-point rounding;
zero capacity rejects every positive demand.
Voltage comparisons allow arithmetic rounding of 1e-12 times the larger
absolute computed voltage and the bound being compared. Minimum and maximum
tolerances are independent and recorded on each sink; a permissive maximum
cannot relax the minimum or admit a negative voltage. This is not a
mesh-accuracy allowance or an expanded operating voltage specification.

An optional nonnegative source current limit is a capacity admission constraint.
Excess demand returns `INFEASIBLE` and keeps the ideal-voltage calculation only
as a requested-load diagnostic. It does not scale loads, determine a lower
source voltage, simulate CV/CC transitions, or model foldback. Sink limits are
checked individually; an unspecified voltage window has a 0 V lower bound and
no upper bound. A feasible result covers only those declared constraints, not
return copper, device undervoltage response, temperature ratings or certification.
Multisink `drop_over_current_ohm` means the worst sink drop divided by total
demand; it is not a two-terminal resistance. Mesh refinement now checks every
sink's drop so a stable worst drop cannot hide another sink's instability.

`test_service_multisink.py` creates a disposable three-pad native board, reloads
it, extracts actual copper through the production mesher and solves unequal
sink demands. It checks source capacity, each sink's identity, legacy voltage
limits, UUID/label duplicate rejection and saved-source hash equality. Native
checks were run on Windows with KiCad 10.0.6 and its Python 3.11.5 runtime.
These saved-board checks do not establish live unsaved-editor behavior.

The native VTK mesh tests check holes, area, boundary containment, separated
islands, point-only contacts, contact-boundary T junctions, many aligned holes,
terminal mapping, via contacts, cancellation and triangle budgets. Contour
triangulation is accepted only after every boundary edge is preserved. Difficult
regions use a constrained Delaunay fallback. No copper boundary is snapped to
another boundary to manufacture connectivity.

## Electrothermal coupling

Validation date: 2026-10-09. Windows, KiCad 10.0.6 and its native Python 3.11.5,
NumPy 2.4.2, SciPy 1.17.1 and Matplotlib 3.10.8. The full Quick PI suite passed
177 tests and 155 subtests; the full QuickTherm suite passed 100 tests and
77 subtests. Both exited normally. Four native-binding deprecation warnings
were reported by each suite. These are source and disposable-package checks;
no installed-plugin or live-editor workflow is claimed.

The [electrothermal audit](../../docs/audits/ELECTROTHERMAL_COSIM.md) records
analytical steady/transient references, independent mesh/time refinement,
conservative heat transfer, material/convergence failures, native dialogs,
saved-source invalidation, report rollback and isolated package execution.
The [study guide](../ELECTROTHERMAL.md) documents units, reviewed inputs,
boundary conditions and unsupported physics. Steady board fields and lumped
transient nodes have separate model coverage; source-current limits are
diagnostic budgets.

## Marble saved-board runs

Validation date: 2026-09-14. KiCad 10.0.5, its native Python 3.11, NumPy, SciPy and
VTK 9.6. The source project remained read-only; all 27 original design-file
SHA-256 hashes matched the pre-run manifest. Each worker had a 45-second limit.
Requests, full responses and concise JSON summaries are in the local validation
directory `.validation/marble/quick-pi`.

All cases use a 1 A sink, copper at 20 C, 25 um barrel plating and a 1 s
adiabatic thermal screen. The first two cases use a 12 V source. Series uses 1 V.

| Net and terminals | Maximum mesh edge | Triangles | Drop | Joule loss |
| --- | ---: | ---: | ---: | ---: |
| `+12V`, R15.2 to R16.2 | 1.0 mm | 99,794 | 0.408474 mV | 0.408474 mW |
| `+12V`, R15.2 to R16.2 | 0.5 mm | 235,624 | 0.489011 mV | 0.489011 mW |
| `+12V`, R15.2 to R16.2 | 0.4 mm | 331,376 | 0.544301 mV | 0.544301 mW |
| `/Power/+12VS`, C131.1 to Q4.1 | 0.5 mm | 60,248 | 2.182053 mV | 2.182053 mW |
| `/Power/+12VS`, C131.1 to Q4.1 | 0.25 mm | 217,823 | 2.256597 mV | 2.256597 mW |
| `/Power/+12VS`, C131.1 to Q4.1 | 0.2 mm | 317,037 | 2.268876 mV | 2.268876 mW |

The complete `+12V` extraction contains 70 tracks, 32 pads, seven zones and 63
vias across twelve layers. The `/Power/+12VS` extraction contains 17 tracks,
15 pads, two zones and 20 vias. These are full selected-net meshes, including
branches and plane geometry, rather than a shortest-track path approximation.

The last `/Power/+12VS` resistance increment is 0.544%, below a 1% comparison
tolerance. Its peak triangle current density changes from 201.947 to
209.523 A/mm2 (3.75%): local peaks require a separate convergence decision.
The `+12V` resistance still changes by 11.31% between the last two meshes; these
runs do **not** establish its mesh-independent resistance or hotspot value.
Global conservation alone does not establish spatial convergence. Refinement
budgets reject oversized meshes rather than silently returning a coarser solve.

The real series case is `U1.M6 -> R161.1 -> R161.2 -> U1.M5`, beginning on
`Net-(R161-Pad1)`. R161 is explicitly assigned 0.005 ohm and 10 nH. The native
solve gives 1 A through R161, a 5 mV component drop, 5 mW component loss,
5.040172 mW copper loss and 10.040172 mW total loss. Stored inductive energy is
5 nJ; its steady-state inductive voltage drop is zero. Difference-based flux
evaluation and iterative refinement retain conservation without reducing the
acceptance criteria.

These results validate a 2.5D DC conductivity model. The thermal screen omits
cooling, heat spreading, temperature feedback, melting and fuse opening. It is
not an AC, transient electromagnetic, electrothermal or certified fusing model.
