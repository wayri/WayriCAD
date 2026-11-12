# Shared Electrothermal Integration: 4.8.3 Source Validation

Release association: **4.8.3**. This is a local source-
validation receipt, not a hosted CI or public-release receipt. Disposable package
checks below predate final release publication; they do not verify 4.8.3 downloads.

## Scope

The heater's new 3D study uses a steady rectilinear finite-volume electrical and
thermal network, not a 2D field displayed with artificial height. It includes
Joule losses, temperature-dependent resistivity, conduction, prescribed ambient
convection/radiation and explicit Kelvin Seebeck/Peltier coupling. Original-cell
fields are rendered offline with Three.js and can be probed, rotated, panned and
zoomed. This 4.8.3 source remains separate from previously published 4.8.2 assets.

Quick PI, QuickTherm and Quick SI reuse the same study controller and CLI kernel.
SI additionally accepts source-bound, explicitly reviewed XYZ temperature samples
for DC resistance correction. It does not silently recalculate HF impedance.
Planar Magnetics separately reuses QuickTherm's layer kernel for spatial primary
winding losses, temperature/resistance feedback and declared core-contact heat.

## Verification

Checks performed on Windows with Python 3.11, the existing scientific runtime,
and KiCad 10.0.6's Python/wx for native-controller checks:

| Check | Observed outcome |
|---|---|
| Shared solver, report intake/integrity, CLI, materials and SI feedback | 73 passed |
| Heater suite | 32 passed, 8 skipped |
| PI suite | 710 passed, 79 skipped; two isolated subprocesses lacked Matplotlib in the initial interpreter |
| PI focused subprocess/mesher rerun in scientific interpreter | 23 passed, 1 skipped |
| QuickTherm suite | 291 passed, 28 skipped; one expected menu inventory changed |
| QuickTherm viewport/menu tests after intentional inventory update | 5 passed |
| SI suite | 219 passed, 39 skipped |
| Magnetics suite including asynchronous thermal lifecycle | 71 passed, 2 skipped |
| KiCad-native shared controller, cancellation/stale-result/export/layout tests | 5 passed |
| Candidate PCM schema, assets, syntax and independent runtime checks | 27 archives validated |
| Extracted heater, magnetics, PI, Therm and SI archives | Actual isolated solve, integrity-checked probe, offline HTML and license checks passed |
| Chromium/WebGL desktop and mobile | Nonblank original-cell geometry, rotation, hover probe and 390px layout passed; no page errors |

Numerical tests include analytical bars, a manufactured 3D temperature solution,
conservation, refinement, Peltier polarity reversal, open-circuit Seebeck,
nonconvergence, material bounds and floating-region rejection. Report tests cover
tampering, duplicate/nonfinite JSON, bounded traversal and a real 50,000-cell
report exceeding the request-size limit. Requests and exported evidence have
separate byte/node budgets. Skips are not compatibility passes.

The native controller tests intentionally disable embedded WebView creation.
Actual Three.js rendering was checked in Chromium, not a running KiCad editor's
WebView; live editor integration still requires manual qualification.

## Pre-publication Corrections And Root Diagnostic

Two source audit findings were corrected before release: the solver dispatches
the tolerance keyword supported by the installed SciPy `cg` (`rtol` or legacy
`tol`), and Heater/Quick SI declare scientific dependencies for independent
managed-runtime provisioning. Standalone solid-study CLI dependencies are exposed
through `wayricad[electrothermal]==4.8.3`; the `si` extra also includes SciPy.
No actual dependency installation was performed by these documentation checks.

The full local root suite returned exit code 0 with **1,159 passed, 147 skipped**
while emitting a non-terminating Windows COM `0x8001010d` diagnostic during wx
event yielding. The global-context cause remains unresolved; isolated checks do
not establish a fix. This is not native WebView/running-editor qualification or
a hosted release CI pass. Existing suite counts above are retained unchanged.

## Reproduction and limits

See [heater workflow and examples](../../heater_designer_plugin/THERMAL_3D.md),
[shared offline equations/help](../../wayricad_runtime/THERMOELECTRIC_3D.html),
and [magnetics thermal workflow](../../planar_magnetics_plugin/THERMAL_STUDY.md).
The help illustration is an actual solved copper-flex browser result; capture
scope and renderer attribution are recorded in
[asset provenance](../../wayricad_runtime/assets/thermoelectric/PROVENANCE.md).

Automatic heater conversion supports a single foil layer; it rejects unmodelled
vias. Explicit 3D requests can represent vertical conducting regions. There is
no 3D transient, fluid flow, contact resistance, bending/stress or qualified
continuum Thomson solution. Construction, material validity, mesh refinement
and boundary evidence remain the user's responsibility. These checks establish
implementation contracts, not measured thermal accuracy or safety approval.
