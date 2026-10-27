# Constant-power DC loads

For one endpoint, specify `sink_terminal` and `load_power_W`. For multiple
endpoints, each entry in `sinks` specifies exactly one of `power_W` or
`current_A`. All demands must be finite and strictly positive. Omit an inactive
load rather than entering zero. The source voltage must be finite and positive.
`source_current_limit`, `min_voltage_V` and `max_voltage_V` retain their normal
feasibility checks. A violated limit is an infeasible requested-load diagnostic;
the solver does not invent source foldback or silently reduce the demand.

```json
{
  "action": "solve",
  "board_path": "C:/Projects/Example/board.kicad_pcb",
  "net": "VCC",
  "source_terminal": "J1.1",
  "source_voltage": 5.0,
  "source_current_limit": 3.0,
  "sinks": [
    {"id": "processor", "terminals": ["U1.1", "U1.2"], "power_W": 4.0, "min_voltage_V": 4.5},
    {"id": "peripheral", "terminal": "U2.1", "current_A": 0.25}
  ]
}
```

Explicitly grouped pads form one ideal equipotential electrode. Its declared
power is the total for the group; contact currents are distributed by the FEM,
not divided equally by pad count. Source pads may also be explicitly grouped.
This ideal connection is a modeling assumption, not a change to board copper.

## Numerical contract

The fixed-temperature copper FEM is linear, but a power load draws
`I = P/V` at its solved terminal voltage. A baseline field solve and one unit
current perturbation per power endpoint produce a reciprocal port resistance
matrix in ohms. No nonlinear iteration remeshes the board. The current solver
assembles/factorizes each basis field separately; the reduced network is reused
throughout the nonlinear iteration. Cost is `number of power endpoints + 2`
FEM solves, including the final field, and a small dense nonlinear port system.

With current-only demands included in open-circuit port voltage `a`, the port
equation is `V = a - R(P/V)`. Damped Newton iteration starts at `a` and remains
on the positive incremental stiffness branch. The result reports its voltage
residual and dimensionless incremental stability margin. The solver rejects
nonconvergence, nonpositive voltage and collapse/marginal points (margin at or
below `1e-5`). It never selects the low-voltage, high-current root to manufacture
a result. For a single resistor, this reproduces
`V = (Vs + sqrt(Vs² - 4RP))/2`, with collapse at `P = Vs²/(4R)`.

The final FEM solve recomputes all fields and quadratic conductor losses using
the converged currents. Each power load must satisfy `V*I = P` within relative
tolerance `1e-8`; source power must equal delivered load power plus conductor
loss within relative tolerance `1e-6`. Existing current and FEM energy balance
checks also apply. `load_power_W` reports total delivered endpoint power,
`requested_constant_power_W` totals declared power demands, and `total_power_W`
continues to mean path dissipation. Mixed constant-current endpoints contribute
their actual `V*I` to delivered power.

This implementation supports 2.5D copper, mixed current/power endpoints and
grouped pad electrodes. It rejects series component paths, package contacts,
3D, resistive-load/sweep combinations, automated mesh-convergence studies,
electrothermal feedback and transient mode. The existing convergence assessment
requires fixed currents between meshes; manually solving successively refined
meshes is supported, but is not an automatic convergence certificate.
Proportional live-current rescaling is disabled for power requests.
Adiabatic heating indicators describe losses at this fixed DC operating point;
they do not imply that power regulation persists as copper heats.

This is a DC operating-point calculation, not a converter control, startup,
transient regulation or dynamic stability simulation. A positive incremental
margin certifies the selected algebraic branch only. Return impedance is not
included unless explicitly represented by a separate supported workflow;
declared power is referenced to the ideal return of this single-net model.
