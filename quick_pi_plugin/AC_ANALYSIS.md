# AC copper analysis for SMPS paths

Included in release 3.6.34. The earlier 3.6.33 installers do not contain this
AC workflow.

[Native, analytical and package validation](../docs/audits/QUICK_PI_AC_2026-10-27.md).

Quick PI's **AC / SMPS copper study** analyzes a declared straight section of
parallel copper conductors, including its explicit return conductors. It uses
the mean current and the RMS currents of individual harmonics. The result is
frequency-dependent impedance, current crowding and average copper heating.
The saved-board DC solver, lumped transient circuit and this cross-section
model are separate workflows with different geometry and assumptions.

## Choose the right workflow

| Question | Workflow | Required information |
|---|---|---|
| What is the board's DC drop and I²R loss? | Ordinary 2.5D DC analysis | Saved copper, stackup, source and sink pads, voltage and current |
| How does DC loss change copper temperature and resistance? | Include Joule heating / temperature feedback | Reviewed thermal materials, cooling, contacts and temperature bounds |
| What do switching ripple and harmonics do to straight copper and its return? | AC / SMPS copper study | Conductor cross-sections, spacing, length, temperature and harmonic RMS currents |
| How does a rail react to a load step? | Transient PI | Explicit R/L/C, ESR, before/after loads and time step |
| How does the switching converter itself behave? | External reviewed circuit simulation | Converter topology, device/control/magnetic models and operating conditions |

An SMPS input loop, output rail or busbar can be represented when a straight,
uniform section and its return are a suitable local approximation. Use currents
from a reviewed switching simulation or a measured waveform. A switching
frequency alone does not determine ripple current or its spectrum.

## Joule heating is already included

Ordinary DC analysis always calculates copper heating. Within each conductor,
`J = −σ∇V` and the local heat rate is `q = J·E = ρ|J|²`, in W/m³. Integrating
over copper volume gives watts; an axial via resistor contributes `I²R`.
The loss tables separate sheet copper, via barrels and explicit series branches.

**Include Joule heating / temperature feedback** adds the steady saved-board DC
thermal iteration. It conservatively transfers those losses to matching thermal
cells, solves temperature, updates local copper resistance and repeats. Missing
material or cooling inputs block the solve. Temperature/material limits and
iteration failure remain explicit failures. Delivered load power is not
implicitly counted as copper or component heat. See
[the full electrothermal workflow](ELECTROTHERMAL.md).

AC copper heating is also Joule heating. The AC study sums the mean-current and
harmonic losses as described below. It uses a prescribed conductor temperature;
its harmonic losses are not silently injected into the saved-board DC
thermal-feedback model. Do not treat a fixed-temperature AC loss result as a
predicted steady operating temperature.

## Set up a study

1. Open **More → AC / SMPS copper study…**. Review or load the explicit model.
2. Describe every straight conductor carrying the modeled current, including
   the return. Give each conductor a unique name and its current scale.
   `x_mm` and `y_mm` are the centre of each rectangular cross-section;
   `width_mm` spans x and `thickness_mm` spans y.
3. Enter the mean DC current, conductor temperature and physical section length.
4. Enter each frequency and its **RMS current**, not peak current. Frequencies
   must be distinct. The current scales describe the same port-current pattern
   at each harmonic; an unrelated rail needs a separate study.
5. Review mesh resolution, surrounding-air extent, numerical checks and the
   frequency/geometry limits before accepting results. Export HTML/JSON to retain
   the explicit inputs and diagnostics.

**Build SMPS waveform…** generates a finite Fourier spectrum for triangular
output ripple or unipolar pulsed input current. Triangle amplitude is
peak-to-peak; pulse amplitude is the on-state current. For harmonic order `n`:

```text
Triangle: I_n,rms = 2 sqrt(2) ΔI / (π² n²), odd n only; mean entered separately.
Pulse:    I_n,rms = sqrt(2) I_on |sin(π n duty)| / (π n); mean = I_on duty.
```

The helper retains at most 32 harmonic orders and records omitted RMS current.
The actual omitted loss can be more significant because AC resistance rises
with frequency. Ideal pulse edges have unlimited bandwidth: use a reviewed
switching model or measured spectrum for actual rise-time effects. Editing the
spectrum removes the generated-waveform metadata so it cannot describe stale
inputs.

Current scales multiply the study current. For a simple outgoing/return pair,
use `+1` and `−1`; their sum is zero. A split return can use `−0.5` and `−0.5`
only when that split is an explicitly reviewed assumption. Do not omit return
conductors or use arbitrary current scales to force a preferred loss result.

All lengths in the input are **millimetres**; frequencies are hertz, temperature
is °C, current is amperes, and rail voltage is volts. Result fields state their
units. An optional PCB records saved-file provenance; geometry is the declared
cross-section, not automatically extracted whole-board AC geometry.

Use the [illustrative SMPS copper input](studies/ac-smps-example.json) as a
starting point, then replace its geometry and current spectrum with reviewed
inputs. It is a synthetic section, not a measured converter or board result.

Command line:

```text
wayricad-pi --ac ac-smps.json --output ac-result.json --html ac-report.html
```

## Mesh, convergence and acceptance

The solver uses a nonuniform, cell-centred finite-volume A–V formulation. It
places boundaries at the declared rectangular conductor edges and refines for
at least four cells across each conductor and three cells per skin depth.
`mesh_step_mm` requests an upper target; the skin/geometry rules can refine
further. `max_cells` is a hard budget. A budget failure stops the study instead
of silently coarsening a physically necessary feature.

The solver doubles the surrounding air padding until the last two boxes agree,
with at most four enlargements (up to 16 times the original padding). It then
compares the coarse mesh with a twice-finer mesh at that **same final magnetic
boundary**. Changing the mesh and boundary together could conceal either error;
the two comparisons are kept separate. `convergence_tolerance` defaults to 0.05
(5%). The numerical current and terminal/field-power checks use a 1e-7 relative
gate. Results that fail refinement/domain checks are **UNCONVERGED**, with
provisional values and reported diagnostics.

These checks compare port resistance and complex impedance. They do not certify
convergence of every local current-density peak; local maps remain cell-based
estimates and sharp-edge peaks need additional refinement. A converged
cross-section result still depends on the physical assumptions; it is not a
whole-board or converter validation.

`relative_permittivity` defaults to 4.2 solely for an electrically-short length
check. The largest harmonic phase length must be at most 0.1 rad:
`2π f max(length, cross-section diagonal) sqrt(relative_permittivity) / c ≤ 0.1`. It does not introduce
capacitance or displacement current into the field solve. Supply a reviewed
value appropriate to the modeled environment. Up to 32 distinct harmonics are
accepted. Copper temperature must remain within −40 to 200 °C.

## Equations and interpretation

The section is uniform along the longitudinal `z` direction. Copper is linear,
isotropic and nonmagnetic at the entered temperature. A sinusoidal RMS phasor
uses the time convention `exp(jωt)`. In conductor `k`, a longitudinal drive field
`E_k` and magnetic vector potential `A_z(x,y)` give

```text
J_z(x,y) = σ [E_k − jω A_z(x,y)]
∇²A_z = −μ J_z
integral over conductor k of J_z dS = current_scale_k × I_rms
```

The current constraints determine the longitudinal drive fields. Solving the
coupled field allows current to crowd near surfaces (**skin effect**) and
redistribute because of neighboring outgoing/return fields (**proximity
effect**). These are not empirical multipliers applied to the DC board map.
The skin-depth scale for a good conductor is

```text
δ = sqrt[2ρ / (ωμ)] = sqrt[ρ / (π f μ)]
```

The model must resolve relevant skin-depth and spacing scales. Conductor
boundaries and the surrounding magnetic domain affect impedance; inspect
refinement and boundary diagnostics rather than accepting a coloured map alone.

For a section of length `l`, the mean-current resistance is

```text
R_dc = sum over k of [ρ l × current_scale_k² / area_k]
P_dc = I_dc² R_dc
```

With RMS phasors, the average harmonic loss is

```text
P_h = l × sum over k of integral[ρ |J_h(x,y)|²] dS
    = I_h,rms² × Re(Z_h)
P_total = P_dc + sum over distinct harmonics h of P_h
I_total,rms = sqrt[I_dc² + sum over h of I_h,rms²]
```

There is **no extra factor of one half** when currents are RMS phasors. Distinct
harmonics are orthogonal in a periodic average, so their cross-terms vanish.
Using `I_total,rms² × R_dc` alone misses frequency-dependent redistribution.
The imaginary part of impedance represents reactive voltage, not dissipated
heat. The reported `ripple_voltage_rms_v` is the quadrature sum of harmonic
**series copper-loop voltage drops** (`|Z_h| I_h,rms`). It is not a prediction
of regulated output-rail ripple; capacitors, source impedance and converter
control are outside this model. `total_current_rms_a` is the RMS study/reference
waveform; each conductor carries its `current_scale` times that waveform.
Compare integrated field loss with terminal real power; an unbalanced result is
not valid evidence of copper loss.

The thermal material law is a local approximation:
`ρ(T) = ρ20 [1 + α(T − 20 °C)]`, with nominal annealed-copper
`ρ20 = 1.7241e-8 Ω·m` and `α = 0.00393 K⁻¹`. A fixed temperature is supplied
for each AC study. Geometry, conductivity and magnetic assumptions must remain appropriate
at that temperature; this is not a melting or phase-change model.

## Low voltage, high voltage and high current

| Application | What this study can calculate | What it does not establish |
|---|---|---|
| Low-voltage, high-current output | Copper impedance, ripple/DC losses and local current crowding for the declared section | Load regulation, transient droop, connector rating or safe operating temperature |
| High-voltage input or bus | The same conductor-loss physics at a reviewed voltage/current operating point | Creepage, clearance, insulation, partial discharge, breakdown or touch safety |
| Fast switching edges | Loss at explicitly supplied harmonics inside the model's frequency/size limits | Radiation, dielectric/displacement currents, common-mode parasitics or complete EMI compliance |
| Thick copper or busbar | Skin/proximity redistribution when the mesh resolves it | 3D bends, branching, contact resistance, via transitions or magnetic force |

Rail voltage does not itself change linear copper resistivity. A 400 V rail and
a 5 V rail with the same copper, temperature and current spectrum have the same
modeled copper loss. This equivalence says nothing about their different
insulation and circuit requirements. High current scales fixed-temperature loss
quadratically; heating can change resistance enough to invalidate that fixed
temperature assumption.

The magnetoquasistatic approximation omits propagation and displacement current.
The section must be electrically short at every supplied harmonic. A small
cross-section mesh does not make a long transmission structure quasistatic.
No magnetic cores, saturation, switching devices, control loops, capacitor ESR,
nonlinear semiconductor loss, dielectric heating or arbitrary routed-board AC
field is inferred. Vias and bends need a suitable separate model.

## References and relationship to this implementation

| Primary source | What it supports |
|---|---|
| [Haus and Melcher, Electromagnetic Fields and Energy, §10.7: Skin Effect](https://web.mit.edu/6.013_book/www/chapter10/10.7.html) | Magnetic diffusion and skin-depth background for sinusoidal conduction. |
| [FEMM 3.4 manual, §3.7.5](https://www.femm.info/Archives/doc/manual34.pdf) | Background on prescribed-current circuit constraints in 2D magnetic analysis. FEMM is not this solver's backend. |
| [COMSOL A–V formulation](https://doc.comsol.com/6.4/doc/com.comsol.help.acdc/acdc_ug_magnetic_fields.08.096.html) | Background on magnetic vector/electric scalar potential field formulations. COMSOL is not the backend. |
| [COMSOL conductor meshing guide](https://www.comsol.com/support/learning-center/article/81171) | Skin-depth resolution and loss-convergence background. This implementation uses its own finite-volume mesh/checks. |
| [Bureau of Standards Circular 31, Copper Wire Tables](https://nvlpubs.nist.gov/nistpubs/Legacy/circ/nbscircular31e2.pdf) | Nominal annealed-copper resistivity and temperature-coefficient background. The linear material law is an approximation. |
| [Quick PI DC solver](solver.py) and [electrothermal coupling](electrothermal.py) | The existing DC field/loss equations, conservative heat transfer and resistance–temperature iteration. |

These references explain physical methods; citing them does not validate a
particular PCB, material assumption, mesh or SMPS design. Inspect the result's
actual convergence and conservation evidence.
