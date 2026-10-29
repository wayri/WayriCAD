# Quick EMerge validation evidence

Development evidence recorded **2026-10-29 on Windows**. This document separates
the current source from the published 3.6.43-beta.1 package. Compatibility
checks are not numerical or hardware qualification. No production PCB was
modified. An isolated development candidate was registered in the running
KiCad 10.0.6 host and launched through its native WayriCAD picker. This proves
the originating-editor development launch, not installed PCM activation.

## Current runtime and certificate

The reused isolated solver is Python **3.11.9**, EMerge **3.0.0b9**, NumPy 2.2.6,
SciPy 1.17.1, Matplotlib 3.11.2, Gmsh 4.15.2, emcad 0.2.0, ezdxf 1.4.5,
msgpack 1.2.4 and msgpack-numpy 0.4.8. Native KiCad is **10.0.6**. The managed
desktop uses a complete wx/Matplotlib backend and VTK; the host's KiCad Python
wx build lacks `wx.svg._nanosvg`, so it is not used as the plotting desktop.
The native bindings remain available for saved-board extraction.

The latest 22-check run after denser sampling and public per-pass refinement
exited successfully in approximately 71 seconds. It reused the existing runtime.
The local evidence is retained under `.validation/quick-emerge-v2/backend/`:
`dense-qualified.json`, `dense-qualified.log`, and the earlier provisioning and
package-preservation records. These local reports are not shipped user assets.
The certificate records:

- UTC completion: `2026-10-29T06:37:04.884492+00:00` (2026-10-29 local date).
- Adapter SHA-256: `36d1bba514cd3e6f37be29a0ead0eefb2bd64f46585109e3164beb21a95b48ff`.
- Scope: **API compatibility smoke solves; not numerical accuracy or convergence**.

All 22 real checks passed:

| Checks | Coverage |
| --- | --- |
| `pcb_line_linear`, `patch_linear`, `pcb_line_adaptive`, `polygon_region_linear` | Basic networks, fields/radiation, bounded adaptivity, saved-region geometry contract |
| `lossy_dispersive_line`, `periodic_floquet`, `scattered_sphere` | Material controls, periodic and scattering APIs |
| `steady_thermal_slab`, `transient_thermal_slab`, `dielectric_rf_heating` | Thermal compatibility adapter and dielectric-loss coupling |
| `bounded_optimization`, `waveguide_te10`, `internal_via_line`, `shunt_resistor_line` | Real-solve parameter search, TE10, internal via and ideal shunt APIs |
| `finite_three_patch_array`, `pml_line` | Multiport/coherent array and PML APIs |
| `import_gds`, `import_gds_xml`, `import_gerber`, `import_odb` | Actual import, mesh, scattering solve and reviewed manifest preservation |
| `network_aaa_fit_rlc_touchstone_reference`, `live_dxf_optycal_consumer_readback` | Network model/reference checks and actual live export publication/readback |

An earlier qualification attempt stopped before the slow PML solve finished
under a 300-second limit and produced no certificate. Provisioning now allows
1200 seconds for the complete gate. Candidate activation still requires every
check to pass. Upstream redirected logs emit Windows character-encoding
warnings for mesh glyphs; the successful process and certificate are the solve
evidence, not an absence of log warnings.

## Focused development checks

- Dependency-manager suite: **20 passed, 6 subtests passed**. It covers candidate
  installation/activation, bounded CAD/export requirements, full-gate timeout,
  unchanged active runtime, failed updates, cancellation, rollback and stale
  certificate requalification.
- Exact provisioning requirements resolved with `pip --dry-run --no-index`
  against the existing solver environment. `pip check` passed. All **53 original
  distributions retained their prior versions**; CAD/export additions did not
  upgrade those dependencies. No new environment was created for this final run.
- Complete shared regression gate: **707 passed, 144 skipped, 502 subtests
  passed**. A native-netlist subprocess first timed out under concurrent solver
  load; the isolated check and complete suite passed with valid inherited
  Windows stdin handles. Skips are not passes.
- Earlier portable plugin gate: **154 passed, 31 skipped, 180 subtests passed**.
  The final full gate after live testing is recorded below. Two standalone-loader
  deprecation warnings remain under Python 3.14.
- Final native component checks: **7 viewport**, **4 workbench**, **5 scene-data**
  and **13 reporting tests passed**. The reporting run reused the bundled
  pure-Python PDF reader; no PDF parseability check remained skipped.
- The managed desktop is Python **3.11.5**, wxPython **4.3.2** / wxWidgets 3.3.4,
  Matplotlib **3.11.2** and VTK **9.7.1**. Canvas tests verify the VTK child HWND,
  enabled interactor, orbit/pan/zoom handlers, original-sample picking and
  front-versus-back volume samples. Hidden/unsolved result views have explicit
  empty states. The live gesture evidence below covers the tested Windows host.
- An extracted local PCM candidate passed independent CLI/runtime checks and
  native frame creation with bundled runtime/assets, a valid icon bundle,
  geometry and enabled VTK interactor. All 139 archive entries compiled or
  passed archive checks as appropriate; no test staging or environment was
  packaged. This is package isolation evidence, not an installed-editor test.
- Actual native KiCad extraction, review custody, isolated solver process and
  publication passed for the two-port coupon without changing source bytes.
  Six viewer modes, linked probing, a line profile and HTML/PDF reports passed
  in the current native frame.

## Published antenna reproduction

The reusable project is
[`examples/quick_emerge/yeo_lee_2019`](../examples/quick_emerge/yeo_lee_2019/README.md).
It recreates the conventional unloaded inset-fed antenna in Figure 1(a) of
[Yeo and Lee (2019), Electronics 8, 502](https://doi.org/10.3390/electronics8050502).
Native KiCad reload and independent polygon checks confirmed the 80 mm square
board/ground, 1266.27 mm² signal copper and 0.76 mm dielectric separation.
Actual saved copper produced one valid 1.66 mm boundary port with no blockers.
A bounded DRC run was stopped without a completed report; the benchmark is not
manufacturing-ready.

The initial coarse workflow retained fourteen actual frequency solves: nine
broad-band samples, three independent narrow-band checks and two mesh checks.
Those historical checks are superseded for convergence assessment by the
controlled study in the example's [comparison](../examples/quick_emerge/yeo_lee_2019/COMPARISON.md).
The later study fixes the 2.6 GHz meshing ceiling, checks both uniform and
adaptive mesh families, validates fitted minima with new FEM solves, and
requires two successive response/bandwidth passes followed by boundary and
global-resolution checks. Matching the paper's resonance on one coarse mesh is
insufficient. The exact minimum depth is not tabulated in the paper.

**Numerical agreement is not qualified.** The current completed refinement
levels and measured resource limits are recorded in that comparison rather
than duplicated here. The finite ABC2 boundary, ideal PEC sheets and unspecified
paper port/de-embedding details remain accuracy limits. API compatibility,
source custody and completed UI workflows do not establish convergence or
antenna performance.

## External patch-feed geometry check

The optional `advanced.patch_feed_extension_mm` defaults to zero, preserving
legacy patch construction. Contract tests cover nonnegative finite values,
substrate bounds, supported study scope, SI geometry arguments and the shifted
ideal port. The focused backend/advanced suites recorded **18 passed, 6 skipped,
27 subtests passed**; the six real advanced tests are opt-in, not passes.

A separate real 4-5 GHz two-frequency patch solve passed result checks with a
5 mm external feed and +0.45 mm patch-center offset. Independent Gmsh mass/bounds checks found one connected
copper surface, area **0.00038 m2**, matching
`(20*20 - 2*3*5 + 2*5) mm2`, and a port at **Y=-14.55 mm**. A separate argument-contract check places
the port at Y=-40 mm for L=31.9 mm, extension=24.5 mm and offset=+0.45 mm
on an 80 mm substrate.
Local evidence is `feed-extension.json`, `feed-extension-checks.json` and
`feed-extension.log` under the backend validation folder. This establishes
geometry/API execution, not agreement with a published antenna resonance or
measured design. The final full 22-check runtime rerun passed after this adapter change.

## Independent numerical checks and limits

- Rectangular-waveguide TE10 cutoff was approximately 6.557 GHz. Comparison to
  analytic propagation gave an S21 complex error of approximately 0.000163 for
  the tested reference case; this is not arbitrary-mode qualification.
- Transient substrate conduction passed equilibrium, monotonicity and timestep
  refinement checks against a one-dimensional Fourier reference. A 1 W to 2 W
  dielectric-heating test retained linear temperature rise. Coupling omits
  copper surface heating and general fluid/conjugate heat transfer.
- Coherent array radiation agreed with an independent sum of per-port complex
  far fields within relative error 1e-10, with total incident power checked
  against the excitation weights. Coarse-mesh deep-null acceptance failed and
  is **not qualified**; no null-depth/gain/efficiency claim is made.
- Network fitting was checked against an independent analytic delay reference;
  asymmetric multiport data checked Touchstone order (legacy two-port order,
  row-major for three or more ports). Fits remain derived sampled-data models.
- The adaptive smoke case deliberately reaches its refinement/sample limits;
  completion is not convergence. Patch resonance refinement, general line
  accuracy, boundary sensitivity, power balance and measured hardware agreement
  remain outstanding. Optional accelerator backends remain unqualified. The
  bundled PARDISO interface passed an actual complex-system residual check;
  same-mesh SuperLU/PARDISO S11 differed by 2.71e-13 at 2.475 GHz. New studies
  prefer PARDISO only after verification; explicit choices remain unchanged.

## Saved PCB region evidence

Earlier native KiCad 10.0.6 tests used a disposable 40 x 20 mm two-layer coupon
with filled B.Cu ground and F.Cu signal. The selected enclosure was X=10-30 mm,
Y=5-15 mm, with 1.53 mm saved dielectric separation. Checks preserved concavity,
holes, actual board intersection, source identity and read-only behavior;
inside vias and invalid cut/return interfaces were rejected. The original
worker and earlier wx UI completed a three-frequency 1-2 GHz two-port solve.
This historical evidence does not establish the redesigned UI's live editor
launch or current physical interaction behavior.

Region extraction still excludes inside drilled features, general multilayer
stacks/via barrels, populated components and interior feeds. Native rule-area
crops and the internal stripline/via template are different workflows. Geometry
custody and API smoke solves do not establish field-solution convergence.

## Earlier release and screenshot provenance

The published **3.6.43-beta.1** package contains the earlier workbench. Its
recorded separate-process checks were **726 passed, 124 skipped, 502 subtests
passed** for the root suite and **86 passed, 5 skipped, 88 subtests passed** for
Quick EMerge. Five native PCB extraction tests also passed separately. Its
extracted installer passed the four-check runtime gate then in use. These are
historical counts, not test results for the current expanded source.

`help-workflow.png`, `help-viewport.png` and `help-region.png` show actual
**earlier beta windows**, not the current compact layout/VTK viewer. Local
interpreter/output paths were replaced by generic paths before capture;
numerical samples, synthetic-board coordinates and port labels were preserved.
The images do not demonstrate a converged antenna or the current layout.
Current live KiCad development acceptance is recorded below.

Current first-open installation into a fresh environment and installed PCM
activation still require separate acceptance evidence. Adapter or qualifier
changes invalidate the recorded certificate; UI-only changes do not alter its
adapter hash. Skipped tests are not passes.

## Live KiCad development acceptance, 2026-10-29

The published-paper KiCad antenna was opened in PCB Editor 10.0.6. The isolated
candidate, with its independently bundled runtime code, was registered in the
real host and selected in the native WayriCAD picker. First open loaded the
actual saved board/rule-area outlines and verified PARDISO. Loading the paper
setup and Preview extracted actual SIGNAL/GND copper with one boundary port
and zero blocking geometry diagnostics. Source bytes remained unchanged.

The physical mouse workflow completed a nine-frequency 2.4–2.6 GHz PARDISO
solve. Orbit dragging, wheel zoom and pan changed the native VTK scene while
the worker ran. A 2D click selected the original E-field sample at
(24, 24, 2) mm, 5896.029 V/m; a distinct 3D click selected (52, 52, 2) mm,
1316.266 V/m. Both represent the solved plane at 2.5 GHz, not arbitrary volume
interpolation. A retained probe was included in HTML/PDF exports.

The embedded report visibly rendered its plots, scope and source-custody
sections. Native WebView load/error events establish readiness without
JavaScript readback. The exported PDF rendered all nine pages; its retained
probe text was checked. Local evidence is `live-kicad-checks.json` and
`paper-benchmark/live-study.html`, `live-study.pdf`, `live-report-contact.png`
under the task validation directory. These are local evidence, not shipped
assets or a convergence certificate.

Live testing found stretched Focus/Image toolbar buttons, a clipped view
selector, a stale pre-report completion message and unnecessary clearing of
the 2D geometry at run start. The fixes preserve compact content-sized buttons,
readable view selectors, reviewed geometry and explicit report lifecycle state.
The final full plugin gate recorded **178 passed, 36 skipped, 192 subtests**. The actual managed VTK desktop
then passed **21 native component tests**, including wide/narrow toolbar layout. The subsequent scalar-color suite passed
**11 native scene tests**, including actual framebuffer comparisons to the
Matplotlib colormap in top/isometric views (within two RGB levels). Scalar
actors remain unlit/opaque while physical geometry keeps normal shading.
A final current-source frame using the retained live result also passed
physical layout/Results/report-preview review, without another FEM solve.
The shared suite recorded **707 passed, 144 skipped, 502 subtests**.

The live nine-point solve deliberately used the coarse historical mesh to test
the complete UI workflow. Its completion is not antenna convergence. The
controlled mesh study and paper comparison remain separate numerical evidence.

## Denser sampling and offline KiCad help, 3.6.44 candidate

The portable plugin gate passed **187 tests, 38 skipped, 194 subtests**. The
shared root gate passed **707 tests, 144 skipped, 502 subtests** after restoring
the required WayriCAD help branding. Windows sandbox hard-link restrictions
required the export gate to run with native permissions; no export assertions
were weakened. Two known standalone-loader warnings remain on Python 3.14.

Twenty data/display tests and a native VTK high-density check retained all
6,561 field points / 6,400 cells and 16,471 radiation points / 16,200 cells.
Original-sample identity was preserved. On this host, field and radiation
renders took about 448 ms and 1,248 ms; these are local timings, not platform
guarantees. Seven final native workbench tests passed, including dense-preset
mesh preservation and the offline help page's native load event. Computer Use
accessibility inspection independently exposed the actual KiCad guide contents;
the locked desktop prevented a new physical contents-link mouse test. Native
WebView text readback was empty despite the loaded document, so it is not used
as the acceptance criterion.

A small-template production StudySession and isolated worker completed **81
actual FEM frequencies, an 81 x 81 field grid, and a 91 x 181 radiation grid**
in about 24 seconds including HTML/PDF exports. All six embedded report figures
were 1800 x 1000 pixels (200 DPI). All 16 PDF pages were rendered and inspected;
export left the original result unchanged. This is high-density workflow
acceptance, not the published antenna or spatial convergence. The earlier
complete nine-frequency result still passes its original configuration digest.
A separate production two-pass refinement run returned all seven requested
frequencies and all four entries of its two-port S matrix, guarding against
stale upstream grid caches after repeated refinement calls.

A separate QA-only immutable adapter snapshot from the earlier study commit
preserves all physical module hashes while production sampling evolves. Repeated
public one-refinement calls reproduced the original two-pass meshes and all six
complex response samples within 2.36e-12. Finer attempts still failed the
unchanged physical-RAM gate. The latest completed paper mesh remains 94,403
tetrahedra and unqualified; user confirmation of additional RAM is pending.
Boundary and global-resolution solves have not run.
