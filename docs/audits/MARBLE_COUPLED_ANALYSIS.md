# Marble: shared-return PI, local SI crosstalk and thermal screening

This records development-source validation on the public Marble PCB. These
changes are newer than release 3.6.21; installing that release does not install
these additions. Numerical completion, model coverage and engineering acceptance
are reported separately.

## Reproduction context

- Run dates: 20–21 October 2026.
- Windows, KiCad 10.0.6, KiCad Python 3.11.5; Gmsh 4.14.1 and VTK meshing.
- Saved Marble PCB: 1,006 footprints, 12 copper layers. PCB SHA-256:
  `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
  Source: [BerkeleyLab/Marble revision a426777](https://github.com/BerkeleyLab/Marble/tree/a426777d92c0f22a546d4740b419a3937e0c1f90/design).
- Analysis reads the saved board, including filled copper. It does not edit or
  refill the source board. The hash is checked before and after the workflows.
- All loads, drive waveforms, cooling coefficients and package thermal
  resistances below are declared test assumptions, not measured operating data.
- Local HTML reports include provenance, geometry and unresolved terms. Native
  saved-file workers were exercised; this is not a live editor interaction test.

## New contracts

| Tool | Added capability | Boundary |
|---|---|---|
| Quick PI | Multiple source pads and multiple pads per load unit | Pads in one unit are ideal equipotential contacts. Total unit current is prescribed; pad currents follow copper conductance rather than an equal split. |
| Quick PI | Several rails use one jointly solved return-copper network | Fixed-current, fixed-temperature 2.5D DC. Shared return loss is counted once; ground rise changes delivered load voltage. AC return inductance and regulator dynamics are outside this model. |
| Quick SI | Local coupled-line modes and near-end step response | Straight parallel sections in supported homogeneous reference geometry. Local sections are not cascaded into a whole-route waveform. |
| QuickTherm | Compact large-board report snapshots | Top, bottom and component-temperature plots remain; interactive geometry, probes, 3D and complete numerical data are retained. `--extended-report-snapshots` requests every static snapshot. |

Grouped PI contacts accept `source_terminals` and per-load `terminals` arrays.
Use an explicit load `id` when mapping it into a shared return. Pad labels or
UUIDs must identify pads on the selected net. Duplicate aliases, ambiguous
labels, disconnected loads and contact overlap between different units are
rejected. Grouping branched SI pins into a two-port model remains unsupported;
the SI tool reports that condition rather than inventing an equivalent route.

See [PI shared-return input](../../quick_pi_plugin/studies/shared-return.example.json),
[SI coupled-route input](../../signal_integrity_advisor_plugin/coupled-routes.json)
and the [command catalogue](../TOOL_CLI_CATALOGUE.md).

## PI cases

The coupled test supplies two actual Marble rails: `+3.3P` at 0.20 A into
U54's seven supply pads, and `+3V3_USB` at 0.15 A into U23's six supply pads.
Both nominal sources are 3.3 V. J21 pads 1, 3, 4 and 13 define the ideal common
ground source; U54 and U23 ground-pad groups draw the corresponding return
currents. All four source-ground pads are deliberately treated as one ideal
external connection.
The DC material assumption is copper at 20 °C, resistivity 1.724e-8 Ω·m,
with saved layer thicknesses and 25 µm barrel plating. This Marble PI run uses
one mesh; conservation and analytical-fixture checks do not establish its
mesh independence or the actual board's operating current distribution.

This large return uses an explicit `max_cells: 2000000` triangle budget.
The default remains 400,000. Increasing this bounded resource allowance does
not coarsen geometry, remove holes or relax the requested maximum edge length.
The CLI also accepts `--max-cells`; shared-return groups declare it in JSON.
Higher budgets require more memory and do not establish mesh convergence.

The normal production worker completes the coupled solve on 1,421,151 vertices
and 1,897,961 triangles, retaining all twelve copper layers.

| Load unit | Total current | Supply drop | Shared ground rise | Delivered voltage |
|---|---:|---:|---:|---:|
| U54 MMC, seven supply pads | 0.20 A | 31.571824 mV | 332.548601 µV | 3.268096 V |
| U23 USB, six supply pads | 0.15 A | 0.265721 mV | 203.072545 µV | 3.299531 V |

Both units meet the test's assumed 3.0 V minimum. Ground-pad groups contain
four U54 pads and five U23 pads. Shared return copper dissipates 96.970602 µW,
counted once; total supply-plus-return loss is 6.451193 mW. Coupled power
balance error is 7.55e-17 W, return current balance error is 1.05e-15 A and
return energy relative error is 2.10e-15. Conservation is a numerical check,
not a physical accuracy certificate.

A separate actual-board contact check uses TPS74401 U36 output pads 1, 18, 19
and 20 as one source, at an assumed 1.2 V, supplying 0.20 A at TP4.1. It solves
with an 11.392 mV copper drop. This demonstrates grouped output-pin contacts;
its ideal return reference does not qualify the complete power loop.

Marble's plated obround holes are preserved. The PI barrel model uses the
capsule perimeter and plating area, native annular contact polygons, and the
actual drill rotation. Unsupported full-3D slot meshing still rejects the
geometry; it does not silently substitute a circular barrel.

## SI results

The MDC/MDIO study uses the saved bounding reference planes `GND3.Cu` and
`GND5.Cu`, finite 35 µm copper, and the saved homogeneous dielectric geometry.
The assumed aggressor is a 3.3 V **open-circuit Thevenin step**, with a 1 ns
10–90% rise. The local four-port model terminates every port in the geometric
mean of the modal impedances. The route's separate 20 Ω driver input is not
used as a termination for this local crosstalk calculation.

| Quantity | Result | Interpretation |
|---|---:|---|
| MDC route delay | About 1.790 ns | Available route estimate; some discontinuities remain unresolved. |
| Modeled MDC/MDIO parallel overlap | 20.625 mm | Local coverage within routes about 254 mm long. End regions are excluded from the uniform cross-section model. |
| Long supported section NEXT peak | 13.070 µV | Approximately 17.625 mm section, 0.673 mm gap. |
| Second supported section NEXT peak | 29.928 µV | Approximately 0.740 mm section, 0.360 mm gap. |
| Very weak third section | Below numerical coupling floor | No precise peak or curve is reported. |
| Local FEXT | Zero in this model | Homogeneous dielectric gives equal modal velocities; this does not establish zero board-level FEXT. |
| LED13/LED14 pair | Unresolved | The selected reference pair does not bound the actual routed layers. |
| Whole SI study | **INCOMPLETE** | Vias, reference changes, unmatched geometry and complete route termination remain unresolved. |

The numerical model checks finite-thickness modal capacitances, reciprocal
coupling, dielectric/scale limits and both modal and weak-coupling refinement.
Independent image/eigenfunction Green functions, a cylinder-over-plane analytic
case and Cohn's centered-stripline reference are used in regression checks.
The peaks above are separate local responses, not a summed whole-route result.

## Thermal results and acceptance

The multilayer test injects U1 = 5 W, U35 = 2 W, U54 = 0.8 W and U23 = 0.5 W.
Board-only heat injection is explicit. Assumed junction-to-board resistances
are respectively 5, 8, 10 and 10 K/W. Their footprint bounding boxes are heat
injection proxies, not qualified package contact models.
This is a separate thermal case: it does not inject the PI study's copper losses
or iterate electrical resistance against temperature.

The environment is air at 25 °C, with copper conductivity 385 W/(m·K),
dielectric conductivity 0.3 W/(m·K), 25 µm barrel plating, emissivity 0.8,
1 m/s declared airflow and a 9 W/(m²·K) board convection coefficient.

At the 64-cell long-axis grid, the numerical solve converges and balances
8.3 W input against 5.292405 W convection and 3.007595 W radiation, with
approximately 7.7e-12 W residual. Junction estimates from the assumed package
resistances are U1 72.516 °C, U35 60.656 °C, U54 44.731 °C and U23 39.930 °C.

The 32→64 mesh check **fails** the unchanged 0.5 °C acceptance thresholds:
component change 0.271 °C, layer-peak change 0.742 °C and field change 1.472 °C.
Heat balance alone is not mesh independence. No actual component temperature
limits were supplied, so temperature-limit acceptance is **UNKNOWN**.

A subsequent 32/64/80 run also **fails**: the final 64→80 comparison gives
0.080057 °C maximum component change, 0.247078 °C layer-peak change,
0.193812 °C source-peak change and 1.411813 °C field change. All thresholds
remain 0.5 °C. The finest-grid result records 220 unresolved barrel stencils;
contact fidelity and spatial convergence remain unresolved.

| Part | Assumed heat | Final board site | Final junction estimate |
|---|---:|---:|---:|
| U1 | 5.0 W | 47.548 °C | 72.548 °C |
| U35 | 2.0 W | 44.576 °C | 60.576 °C |
| U54 | 0.8 W | 36.755 °C | 44.755 °C |
| U23 | 0.5 W | 34.892 °C | 39.892 °C |

The final solve balances 8.3 W against 5.292437 W convection and 3.007563 W
radiation, with approximately 6.0e-12 W residual. These are screening results
with the assumptions above, not qualified component operating temperatures.

## Regression and packaging evidence

- Root suite: 488 passed, 88 skipped, 222 subtests.
- PI native unittest suite: 295 passed; 16 additional pytest function tests
  passed. Portable PI checks: 270 passed, 28 skipped, 229 subtests.
- Explicit mesh-capacity, solver, shared-return and native grouped-contact
  checks: 44 passed. Portable capacity/refinement/shared-return checks:
  20 passed, three skipped, 58 subtests passed.
- Final portable capacity/containment/shared-return checks: 21 passed,
  one native-only check skipped, 128 subtests passed.
- SI native suite: 118 passed, one optional external runtime check skipped.
- Portable SI coupled-model checks: 22 passed, three native-only checks
  skipped, 18 subtests passed.
- Therm report checks: 12 passed.
- Dense PI report and affected report/probe checks: 28 passed. An actual
  Agg-rendered fixture with 1,103 circular/rotated-slot contexts exported in
  0.881 s. Large reports retain every context path in batched collections,
  use three static maps by default, and preserve interactive/numerical data.
- Batch-reference export checks: 29 passed. Child JSON descriptors resolve to
  exact locations in one complete parent archive; physical return descriptors
  declare their sign transforms. Standalone exports keep complete paired JSON.
  Parent data, Unicode round-trips and source-change refusal were checked.
- Managed-runtime selection checks: 18 passed with no installation/network
  calls. Explicit Gmsh selections in batch rails, independent returns and
  shared-return groups request Gmsh before launching the worker.
- Local-refinement, existing native mesh, plated-slot, contact-clipping and
  grouped-service checks: 32 passed. A reference conductor uses 30 triangles
  within a 50-cell budget, where uniform refinement would require 104;
  resistance, I²R and current conservation still meet the analytical checks.
- Conservative containment-candidate pruning and affected native mesh checks:
  32 passed. A synthetic 1,500-hole / 100,000-point benchmark changed from
  9.869 s to 0.402 s with bit-identical membership. This measures that predicate
  step, not the complete board workflow.
- Candidate independent PCM packages: all 23 pass metadata, runtime, action,
  icon and syntax validation. This does not establish native GUI compatibility
  on other operating systems.
- Isolated PCM native checks solve grouped supply/load contacts and a joint
  return using Gmsh, and evaluate the installed SI finite-thickness coupled
  model. The joint-return fixture balances power to approximately 1.8e-15 W.

Plots are generated from the actual saved-board results. The embedded browser
does not allow local-file navigation, so HTML browser interaction was not
claimed as verified. Static scientific previews were inspected locally.

Timed-stack diagnostic runs exited with access violations during corrupted
traceback capture. Those runs are not the final evidence. The normal production
PI worker, without the diagnostic watchdog, completes and saves its full result;
report export is checked separately from that preserved result. This isolates
the validation phases without assigning an unproven native crash cause.

On the same preserved Marble result, the original complete batch export took
432.328 s. The optimized export took 284.454 s in a subsequent run. These are
observed single-run timings, not a controlled benchmark. Child descriptors are
2.2–2.8 KB; one complete parent archive retains the numerical arrays. All
published report files and the source board passed the final consistency checks.
