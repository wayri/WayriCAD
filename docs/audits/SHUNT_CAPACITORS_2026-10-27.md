# Individual shunt capacitors — 27 October 2026

## Scope and workflow

Quick PI standalone rail transients support explicit per-load banks and finite
prescribed current ramps. Each branch has a unique ID, positive effective C,
nonnegative ESR and nonnegative total part/connection ESL. The bank replaces
aggregate C/ESR. DC copper extraction does not supply missing parasitics.

Saved-board discovery uses footprint/pad UUIDs, confirmed total pad count and an
explicit signal/return pair. Unit-bearing values such as `100nF` or
`CC0402_100NF_25V` may prefill. Ambiguous bare codes are not decoded; inclusion,
bias derating, ESR and ESL remain reviewed inputs. Exact public Marble discovery
found three +12V/GND, one /Power/+12VS/GND and 45 +3V3/GND candidate capacitors;
all unit-bearing C values parsed. The board hash remained
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
This establishes inventory matching, not extracted transient equivalence.

## PI equations and checks

Let A map each capacitor branch to its load node, q be charging-positive branch
currents, d prescribed load demand and v the individual internal capacitor voltages.
Feed currents are `i = A q + d`. With shared/path inductance P and resistance Q,

```text
M = diag(ESL) + Aᵀ P A
R = diag(ESR) + Aᵀ Q A
M q' + R q + v = Vs·1 − Aᵀ Q d − Aᵀ P d'
diag(C) v' = q
Vload = Vs·1 − Q i − P i'
```

The generalized passive network retains unlike branches. Exact topology nullspaces
handle ideal algebraic capacitor constraints; positive inductances are not rounded
to zero. Initialization is the pre-step DC operating point. Finite linear current
ramps retain both one-sided slope-boundary samples: inductor currents and capacitor
voltages remain continuous while node voltage may jump. An incompatible ideal
zero-rise step is rejected instead of inventing impulse behavior.

Backward Euler checks charge, KVL and energy. Physical ESR/copper heat is separate
from numerical damping. A fixed-model half-step repeat reports per-load and
per-capacitor differences. Advice uses modes after eliminating algebraic constraints
and at least 20 intervals across finite rises. These are starting points, not
convergence certification. A numerical review caught and corrected spurious mode
advice when an ideal capacitor was split into equivalent parallel parts.

Limits are 128 total shunt/aggregate branches, 10,000 coarse intervals and a scalar
trace-value budget. The solver rejects excessive work. Standalone current-driven
transients only; explicit banks are rejected in coupled electrothermal stepping.

## SI circuits and references

SI banks are explicit source/receiver additions to supported exported native
KiCad/ngspice circuits, each with distinct series R/L/C symbols and ideal common
ground. IDs/attachment provenance remain in the manifest and symbols. Missing
capacitance is rejected. The illustrative eye is unchanged and route-only timing
advice warns that capacitor resonances need additional refinement. Unmodeled
physical branches and extra-pad topology guards are not waived.

The [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
defines the passive capacitor/inductor elements and transient controls. Native
KiCad netlist checks confirmed actual signal/return connectivity. Installed
ngspice passive RC and RLC reference simulations matched analytical charging and
overshoot cases; these checks do not qualify a complete IBIS channel.

## Verification actually performed

Windows, KiCad 10.0.6 / Python 3.11.5 / NumPy 2.4.2 / SciPy 1.17.1. The portable
numerical environment used Python 3.14.2 / NumPy 2.4.2 / SciPy 1.17.0.

- Both runtimes passed the original 16 and new 14 transient numerical tests.
- Additional native dense-bank test: 45 identical branches match their exact
  symmetric equivalent; the 129th branch is rejected. The final native numerical
  run passed all 31 tests. This equivalence is a test, not a general reduction of
  unlike capacitors.
- Additional matrix-exponential checks covered 24 equivalent cases, mixed ESL,
  finite-rise voltage jumps and two loads with overlapping ramps. Errors reduced
  under step halving; charge/energy residuals were around 1e-13.
- Native editor checks passed for required parasitic inputs, exact saved-net
  candidates, narrow-window text and scrolling, quick/advanced roundtrips,
  aggregate replacement, finite-rise solving, branch plot selection and stale
  result clearing.
- SI: 35 native tests passed without skips, including ngspice and native KiCad
  netlists. Portable SI: 172 passed, 17 native capability skips.
- Shared suite at integration: 630 tests, 506 passed and 124 capability skips.
  The additional capacitor table/unit test passed in the final seven-test report run.
- Portable PI using its configured CI scope: 470 passed, 81 capability skips and
  492 subtests before the final dense-bank test. The initial broader command's
  11 meshing failures were all missing VTK in portable Python; the full 16-test
  meshing module passed separately in KiCad's supported VTK runtime.

## Native screenshots and reproducible example

PI images `help-shunt-capacitors.png`, `help-shunt-transient.png` and
`help-shunt-response.png` are genuine native client captures of
[the supplied model](../../quick_pi_plugin/studies/transient-shunt-bank.json).
No board was opened: all R/L/C/edge inputs are explicit. The 5 µs, 1 ns-step
example has 5,003 event-aware samples, minimum load voltage 3.038876 V and maximum
load-voltage half-step difference 29.60 µV. Its finite window does not establish
settling or hardware behavior. A failed capture with reversed window ownership
was rejected; the final capture used the correct parent/child dialog lifecycle.

The SI screenshot is a manual native editor example, with no PCB opened. Values
are explicit source/receiver shunts; no waveform is claimed by the screenshot.
Opaque RGB captures were inspected for clipping and private metadata. Original
private projects were untouched. Final package checks are recorded below.

## Final candidate packaging checks

All 24 independent candidate PCM archives passed their schemas, entrypoints,
icons, bundled runtime and Python syntax checks. The extracted PI implementation
passed 38 native/runtime tests without skips; SI passed 35 without skips. Tests
were staged externally, while production module paths and payload bytes came
from each installer. The candidate wheel passed isolated CLI/report/mechanical
and Analytics Studio checks, including solving the new shunt example and writing
its per-capacitor HTML/JSON report. No local plugin was installed.

The source versions are prepared for 3.6.40. The public PCM feed and stable
release remain unchanged until a separate release is published.
