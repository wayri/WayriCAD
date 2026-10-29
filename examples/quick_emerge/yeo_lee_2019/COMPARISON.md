# Published antenna comparison

This reproduction uses the conventional **unslotted, unloaded antenna in
Figure 1(a)** of [Yeo and Lee, Electronics 2019, 8, 502](https://doi.org/10.3390/electronics8050502),
not the slotted antenna in the paper's title.

**Numerical convergence is not established.** Live KiCad setup, actual saved-copper
simulation, interactive views, linked probes and HTML/PDF reports passed the
development acceptance workflow described in the plugin's
[validation record](../../../quick_emerge_plugin/VALIDATION.md).
That coarse-mesh UI run is separate from the controlled refinement study below.

## Geometry and model

The saved KiCad board has an 80 x 80 mm substrate and full ground, a 40 x 31.9 mm
patch, 1.66 mm feed, 24.5 mm external feed, 9 mm inset, and 2.8 mm clearance on
each side of the inset. RF-35 is modeled with relative permittivity 3.5,
loss tangent 0.0018 and 0.76 mm dielectric separation. The 35 micrometre copper
thickness in the drawing is an assumption; the FEM uses ideal PEC sheets.
One 50 ohm ideal boundary port feeds the actual SIGNAL/GND copper clipped by the
rule area. Source SHA-256:
`cb142949d21442fb842cc958e767b3afb9b678136d6cf0ce21cf2bf6edd2fb94`.

The controlled EMerge 3.0.0b9 study uses second-order mixed elements, ABC2 at
30 mm, global resolution 0.30, and a fixed **2.6 GHz meshing ceiling** at every
level. PARDISO agrees with SuperLU on the same mesh to 2.71e-13 in complex S11.
This solver agreement does not establish spatial convergence.

## Mesh study

| Refinement | Tetrahedra | Fitted resonance [GHz] | Maximum complex S11 change |
|---|---:|---:|---:|
| Uniform 3 mm | 15,991 | 2.471175 | -- |
| Uniform 1.28 mm | 44,827 | 2.496100 | 0.16802 |
| Uniform 1.024 mm | 56,486 | 2.499375 | 0.13023 |
| Uniform 0.8192 mm | 70,838 | 2.500850 | 0.06052 |
| Uniform 0.65536 mm | 80,219 | 2.502450 | 0.06262 |
| Adaptive 1 | 53,746 | 2.506450 | 0.39254 |
| Adaptive 2 | 64,789 | 2.510725 | 0.16718 |
| Adaptive 3 | 78,148 | 2.512875 | 0.08573 |
| Adaptive 4 | 94,403 | 2.514125 | 0.04916 |

Uniform and adaptive meshes form separate comparison families. Each response
uses five actual FEM frequencies spanning 2.460-2.530 GHz, a complex rational
[2/2] interpolation, and an independent FEM solve at its fitted minimum.
Minima are located on a 25 kHz grid. Fitted VSWR crossings are estimates;
both edges have not been independently solved in this controlled study.

Acceptance requires **two successive qualifying mesh comparisons**: resonance
shift at most 0.1%, maximum complex S11 change at most 0.02 (including common
actual FEM anchors), and each VSWR=2 edge shift at most 1 MHz. Then separate
30-to-45 mm air-boundary and 0.30-to-0.20 global-resolution checks must pass.
Geometry, materials, source hashes and frequency anchors must agree; a new
family cannot inherit a convergence streak. None of the completed comparisons
has passed all limits. The finer uniform 102,730-element run was stopped before factorization by a
RAM preflight. Later investigation found that the first preflight conservatively
double-counted retained symbolic storage. A corrected guard now preserves a 20%
reserve against both pre/post-symbolic measurements and the original absolute
reserve; no earlier failed run was retrospectively accepted.

The next adaptive mesh reached **114,033 tetrahedra** and its own checkpoint was
saved. A fresh-process response still failed all corrected RAM checks and
produced no accepted samples. Its measured shortfall was approximately **1.23 GiB
of sustained additional free RAM** at that stage; later levels may need more.
The study is checkpointed pending additional resources. Public size-stop
refinement reproduced the two-level reference within 2.41e-12 complex S11;
locally generated checkpoint save/reload reproduced six samples within 4.60e-12.
These verify execution equivalence, not spatial convergence.

## Comparison with the paper

| Quantity | Paper | Latest completed adaptive result |
|---|---:|---:|
| Simulated resonance | 2.500 GHz | 2.514125 GHz (+0.565%) |
| Measured resonance | 2.528 GHz | 2.514125 GHz (-0.549%) |
| Simulated VSWR < 2 interval | 2.490-2.510 GHz | 2.504772-2.523480 GHz, fitted |

The latest completed mesh has 94,403 tetrahedra and its independent
minimum holdout differs from the fit by 6.69e-06 in complex S11.
That checks interpolation locally; it does not qualify the mesh. The paper does
not tabulate the exact S11 minimum depth, so no depth-agreement claim is made.
The shift between refinement levels remains material even where a coarse mesh
happens to match the paper's simulated resonance closely.

Ideal conductor sheets, the finite ABC2 air boundary, and unspecified paper
connector/port/de-embedding details limit the comparison. Gain, radiation
efficiency, connector fidelity and manufactured-board performance are not
qualified. A bounded native DRC run did not complete; this is a simulation
benchmark rather than a manufacturing release.

`emerge-setup.json` and `emerge-narrow-setup.json` retain the earlier coarse
production configurations for reproducibility. They do not reproduce the later
controlled adaptive study or certify convergence. The study's detailed logs,
criteria, original solves and source hashes remain local validation evidence;
no runtime, generated result or private path is shipped in this example.
