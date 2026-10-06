# <img src="resources/icon-96.png" width="48" height="48" alt="QuickTherm icon"> WayriCAD QuickTherm

QuickTherm is an independently installable KiCad PCB Editor plugin for read-only, steady-state thermal screening. It has its own PCM package, toolbar action, native window, icon, command-line interface and HTML/JSON export. It does not require Quick PI to be installed.

The separate `wayricad-therm-transient` command runs an explicitly parameterized, four-board lumped RC transient screen. It uses saved-board source hashes and KiCad reference checks, a declared fan P–Q/system operating point or prescribed-flow sensitivity case, explicit serial or parallel-passage airflow topology, optional package/body and isolated-sink paths, and ohmic R(T) loss feedback. The parallel model warms air from high X to low X within each board and retains a user-entered passage flow split; it is not CFD. See the [transient model guide](TRANSIENT_MODEL.md) for the input contract and limitations. This does not make the native board viewport a transient copper-field solver.

For the separate steady multilayer model, set `"source_refinement_factor": 2` inside `thermal_network_settings` to subdivide rectilinear cells near mapped footprint sources. A CLI JSON config can also include `"mesh_acceptance": {"grid_cells_long_axis": [24, 48, 80], "maximum_change_c": 0.1, "minimum_source_cells": 4}`. The solver repeats the same saved geometry on increasing grids and reports PASS/FAIL from the two finest component, source-peak, layer-peak and spatial-field temperatures, numerical balance and effective source-contact coverage. An optional phase-shifted solve exposes grid sensitivity. A failed or absent mesh gate must not be read as a converged local hotspot result. Source-aligned refinement is a rectilinear screening mesh; it does not resolve package-to-copper contact geometry or qualify physical hotspots.

Start with the [step-by-step user guide](QUICK_THERM_USER_GUIDE.md) or its [offline HTML version](QUICK_THERM_USER_GUIDE.html). The [model and limits](QUICK_THERM.md) explain the equations and supported evidence.

An [experimental Gmsh/CalculiX bridge](CALCULIX_BRIDGE.md) can prepare a layered steady-conduction deck from a saved board and reviewed power/boundary inputs. It rejects vias, mounting contacts and cooling physics it cannot yet model; its CalculiX FRD output is not interpreted as a QuickTherm board or junction temperature.

![QuickTherm field mapping and board preview in the native window](examples/quicktherm-native-window.png)

![QuickTherm expanded board view with a temperature scale and component estimates](examples/quicktherm-large-board-view.png)

![QuickTherm approximate board-midplane temperature overlay from the optional heat model](examples/quicktherm-board-model-view.png)

![QuickTherm simultaneous top and bottom board workspace with shared temperature scale and cross-selectable component table](examples/quicktherm-paired-workspace.png)

The paired-workspace screenshot was captured from the native KiCad Python window using a synthetic 60 × 40 mm board outline, two invented components and illustrative layer-temperature arrays. It demonstrates the UI only; the temperatures are not measured or solver-qualified results.

The **Open top + bottom workspace** button opens simultaneous front and mirrored-back thermal views with a live cursor readout, probe placement and a component summary that cross-selects with the plots and PCB Editor. Top and bottom maps display labelled component junction estimates with a translucent, same-side interpolation where enough mapped points exist. The optional board conduction model provides an approximate board-temperature overlay; it needs material, airflow and boundary inputs. The first expanded map above is **not** a computed board-surface temperature. The second view is the optional thin-sheet model, using an assumed 35 W/(m·K) in-plane conductivity, 0.8 emissivity, 10 m/s forced airflow, a 48-cell long-axis grid and the saved 1.6 mm thickness. Those inputs are illustrative, not measured properties of the fixture.

The [component-results screenshot](examples/quicktherm-native-results.png) shows the sortable temperature table and summary in the same native window.

Open a saved board in KiCad PCB Editor and launch **WayriCAD QuickTherm**. Choose only the dissipating components, review the ambient temperature, then use **Enter component inputs…** to supply power and the applicable thermal resistance for each selected part. No saved `Power_W` or `RthetaJA` fields are required for this path, and the PCB is not modified. If your board has complete thermal properties, switch to **Use saved footprint fields** and map them. Both paths show top and bottom views, contours, a 3D overview, a component temperature table, and cross-selection back to PCB Editor. Optional virtual heatsinks and board models include thin-sheet and layer-resolved copper/vertical-path approximations. The report records input provenance, assumptions, coverage and heat balance where applicable. The viewport board models remain steady-state; the separate transient CLI is a lumped RC screen, not CFD or a spatial transient copper-field solver.

For automation, install the source wheel and use `wayricad-therm`:

```text
wayricad-therm C:/Projects/Example/board.kicad_pcb --environment air --power-field Power_W --theta-ja-field RthetaJA --thermal-refs U1 U2 --html quicktherm-air.html
```

### Reproducible example

The public [demonstration PCB](examples/thermal-demo.kicad_pcb) has four hypothetical dissipating parts spread across a 60 × 40 mm board. From the repository root with KiCad 10 native Python and the declared dependencies available:

```text
python -m quick_therm_plugin.cli quick_therm_plugin/examples/thermal-demo.kicad_pcb --environment air --power-field Power_W --theta-ja-field RthetaJA --thermal-refs C1 C2 C3 J1 --ambient 20 --html quicktherm-demo.html
```

The actual run produced the [JSON summary](examples/thermal-demo-result.json) and [self-contained HTML report](examples/thermal-demo-report.html). The result was generated with KiCad 10.0.6 on Windows; the public example files use relative paths.

| Part | Power | Supplied RθJA | Estimated junction at 20 °C ambient |
|---|---:|---:|---:|
| C1 | 0.20 W | 45 K/W | 29.0 °C |
| C2 | 0.45 W | 35 K/W | 35.75 °C |
| C3 | 0.10 W | 65 K/W | 26.5 °C |
| J1 | 0.30 W | 50 K/W | 35.0 °C |

These are independent `ambient + power × RθJA` estimates. The sample board is a visual fixture with hypothetical fields and repositioned parts, not a routed design or thermal qualification. To regenerate it from the repository fixture, run `examples/build_demo.py`, then run the command above. The example report contains board views and assumptions; the JSON summary is a small subset of the full report evidence.

For the board-model view and automatic limits, use the reviewed [example configuration](examples/thermal-demo-config.json):

```text
wayricad-therm quick_therm_plugin/examples/thermal-demo.kicad_pcb --config quick_therm_plugin/examples/thermal-demo-config.json --html quicktherm-demo.html --require-limits-pass
```

The saved example converged with 1.05 W input and a heat-balance residual below 10⁻¹² W. The resulting board-midplane range is about 23.6–27.6 °C, with four component limits passing and two virtual probes recorded. This is a model output under the declared forced-air assumption, not a measurement. The displayed `Tj≈` labels in the board-model view come from the model and mapped `RthetaJB` fields; the simpler table above uses the separate `RthetaJA` screen.

The PCM action uses the native KiCad Python runtime and launches a separate bounded worker for board analysis. Each installed QuickTherm ZIP carries its own shared runtime files, so it never imports a sibling plugin package.
