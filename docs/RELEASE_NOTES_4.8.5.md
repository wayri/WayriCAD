# WayriCAD 4.8.5

## Release Status

This release contains the PI/SI source changes on top
of 4.8.4. The suite retains 27 independently installable packages and the
existing Portable Web Export source-freshness guards and WebView 0.6.0 pin.
Version alignment is not evidence of a published release or local installation.

Live originating-editor checks passed on Windows with KiCad 10.0.6. Native
tests, hosted CI, isolated package checks and public download/hash verification
are distinct evidence. The release's `validation-4.8.5.json` receipt identifies
the exact source revision, hosted run and artifacts. No new KiCad 11
compatibility is claimed.

## PCB-Driven PI And SI Workflows

- Quick PI follows a selected net in the originating PCB Editor while idle.
  Explicit Source pad and Load pad actions assign endpoint roles; selection
  order never establishes current direction. Ambiguous or stale selections do
  not silently choose a different topology. Save and reload changed geometry.
- Quick SI exposes Use PCB selection and idle Follow PCB on its toolbar, using
  the existing guarded path-selection workflow. Endpoint direction remains
  explicit. Read failures pause following; close stops the follower and queued
  callbacks are lifetime-checked. Existing cross-selection actions remain.
  Standalone windows without an editor identity start with following off, so
  background connection errors do not overwrite analysis guidance.
- The PI power-path diagram presents sequential source, copper rails, device
  banks and load with stage numbering, directional arrows, zoom, pan and SVG
  export. Parallel devices retain pin groups and model evidence. Ground is not
  inserted as a forward-path stage, and missing converter models are not guessed.
- The series editor separates Auto, Console and Bundle views with an embedded
  Diagram/Details preview. Choose explicit source/sink pads, discover candidate
  routes, select an alternative and review each stage. Component, current-pin
  and model controls correct a valid stage without silently dropping parallel
  banks or multi-pad electrodes. Replacing those groups requires confirmation.
  Invalid drafts clear the diagram/tree and disable Run/Save. The preview is
  topology only: it does not fabricate solved voltage, current or power.
- Named bundle cases reuse the same editor and preview when selected. Cases
  retain their individual path, models and operating values; this is not a new
  arbitrary coupled branching-network solver. Existing source checks, guarded
  save/load and cancellation contracts remain.

Following editor selection does not read unsaved geometry into the numerical
model. These are review workflows, not board-editing or automatic signoff tools.
See the [PI guide](../quick_pi_plugin/README.md#pcb-driven-setup-and-sequential-paths)
and [SI guide](../signal_integrity_advisor_plugin/ReadMe.md#pcb-driven-workspace).

## Two Distinct Impedance Models

### Explicit MQS Two-Port Sections

Quick PI's AC two-port workflow computes the complete complex Z11/Z12/Z21/Z22
matrix for explicitly specified straight, parallel rectangular copper
conductors and two independent current-loop ports with explicit returns.
It reuses one sparse factorization for both excitations at each frequency and
mesh; this is not a measured runtime ratio or a Palace performance comparison.

The magnetoquasistatic (MQS) model includes supported skin/proximity current
redistribution and conductor Joule loss. It has no distributed capacitance,
dielectric loss, displacement current, radiation, arbitrary bends/vias/zones,
automatic board-wide AC geometry or nonlinear converter simulation. Relative
permittivity is a size-validity guard, not capacitance in the MQS equations.
`CONVERGED` means the implemented mesh/air-boundary sensitivity checks passed;
`PROVISIONAL` retains unmet sensitivity evidence. Neither is physical validation.

Use **More > AC two-port impedance**, or:

```text
wayricad-pi --ac-ports study.json --output impedance.json --timeout 300
```

See [input, equations, units and numerical checks](../quick_pi_plugin/AC_PORTS.md).

### Quasi-TEM Planar PDN Cavity

The separate planar model uses an explicit triangle mesh, homogeneous dielectric
separation/permittivity/loss and a resistive copper sheet above an explicitly
assumed full ideal equipotential reference plane. Magnetic-wall (Neumann) edges
are perfectly reflecting. Distributed capacitance supports in-plane cavity
resonances; this is a scalar quasi-TEM parallel-plate model, not the MQS section
model, full-wave extraction or a Palace integration.

The board workflow uses saved copper and two selected positive pad groups,
both relative to that common ideal reference, not a differential pair or DC
termination. It binds configuration and extracted geometry to the reviewed
saved-board snapshot and rejects changed inputs, 3D mode, multilayer copper,
plated barrels/stubs, noncoplanar or nonuniform-thickness meshes, disconnected
meshes and overlapping ports. Reference-plane coverage and voids are assumed,
not automatically audited from the board.

Sheet resistance is an approximate DC/skin envelope, not exact finite-thickness
surface impedance. Return-plane loss, internal conductor inductance, roughness,
fringing, radiation, vias/launches, plane-stack coupling, discrete components
and dielectric dispersion are omitted. Narrow traces comparable to plane
separation are not accuracy-qualified. Mesh and frequency sampling need user
refinement and can miss narrow resonances. Results remain **`MODELLED`**, with
convergence **`NOT_EVALUATED`**; there is no automatic convergence claim.

Use **More > Planar PDN impedance from selected pad ports**, or:

```text
wayricad-pi --plane-ports study.json --output impedance.json --timeout 300
```

The planar CLI returns 3 for `MODELLED` evidence, not a convergence pass. See the
[model contract](../quick_pi_plugin/PLANE_PORTS.md) and
[saved synthetic example](../quick_pi_plugin/examples/planar_pdn/README.md).
The example compares this implementation's fine and coarse meshes; it is not
an independent solver comparison, board measurement or native-window capture.

## RLC Zones, Vias And Residual Barrels

Filled-zone corridor connectivity and reference-overlap estimates remain
explicit first-order models, not arbitrary spreading-current solutions. Via
lengths now use saved physical stackup distances and TopLayer/BottomLayer spans,
including unflashed internal annuli; equal layer spacing is not substituted.
Reports separate physical, traversed and residual barrel spans. Via-row feedback
and notes expose the lengths; bulk slices do not invent a terminal path.

Residual barrel may be an open stub or a connected branch. Its termination,
capacitance, resonance and input impedance remain unknown without a validated
via/channel model. Such paths, branched routes and reference ambiguity retain
blockers/partial status; frequency sweeps do not present a complete series
impedance for them. Duplicate physical pad labels cannot bridge a copper gap.
Backdrilled/stepped barrel and microvia taper physics are not solved. See the
[coverage audit and evidence](../trace_impedance_plugin/RLC_ZONE_VIA_AUDIT.md).

## Results, Comparisons And Publication

The result viewer retains every original complex sample in ohms at frequencies
in Hz. Log-log magnitude panels, pan/zoom and hover probes expose original
frequency, real/imaginary impedance and phase. Zero magnitudes are omitted from
log curves, not replaced with a fabricated floor in stored data.

Imported reference JSON must declare Hz/ohm units and all four matrix entries.
Signed differences use `20 log10(|Zmodel| / |Zreference|)` only at common,
nonzero samples (relative frequency tolerance 1e-9), without interpolation or
extrapolation. Match geometry, material, ports and boundaries before inferring
accuracy; a reference filename is not proof of its provenance. Saved comparison
results retain the complete imported dataset and comparison basis.

Inputs and references are bounded, validated and hash-checked for guarded
publication. Editing/cancelling invalidates pending explicit-MQS generations;
close prevents their UI delivery. Sparse factorizations are not forcibly
interrupted: cancellation/time budgets are cooperative between solves.
Publication guards are revision checks, not operating-system source locks.

## Validation And Continuing Limits

The [live acceptance record](audits/PI_SI_LIVE_4.8.5.md) records 18 checks against
an isolated originating PCB Editor, including bidirectional selection, ambiguous
selection recovery, real saved-board PI/SI analyses and stale-source rejection.
Fourteen native wx regressions passed. These are not a new screenshot review:
desktop capture returned an occluded foreground application, which was not used
as visual evidence. Solver, plotting and package checks remain separately listed
in the final release receipt; skipped tests are not passes.

All existing DC PI, board-RLC SI eye, electrothermal, fabrication and native-host
limits in [4.8.4](RELEASE_NOTES_4.8.4.md) and
[4.8.3](RELEASE_NOTES_4.8.3.md) continue to apply. No Palace equivalence, measured
hardware accuracy, manufacturing approval or protocol compliance is claimed.
