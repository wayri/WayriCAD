# <img src="resources/icon-96.png" width="48" height="48" alt="QuickTherm icon"> WayriCAD QuickTherm

QuickTherm is an independently installable KiCad PCB Editor plugin for read-only, steady-state thermal screening. It has its own PCM package, toolbar action, native window, icon, command-line interface and HTML/JSON export. It does not require Quick PI to be installed.

Start with the [step-by-step user guide](QUICK_THERM_USER_GUIDE.md) or its [offline HTML version](QUICK_THERM_USER_GUIDE.html). The [model and limits](QUICK_THERM.md) explain the equations and supported evidence.

![QuickTherm field mapping and board preview in the native window](examples/quicktherm-native-window.png)

![QuickTherm expanded board view with a temperature scale and component estimates](examples/quicktherm-large-board-view.png)

![QuickTherm approximate board-midplane temperature overlay from the optional heat model](examples/quicktherm-board-model-view.png)

The **Expand board view** button opens a resizable thermal viewport. Top and bottom maps display labelled component junction estimates with a translucent, same-side interpolation where enough mapped points exist. The optional board conduction model provides an approximate board-temperature overlay; it needs material, airflow and boundary inputs. The first expanded map above is **not** a computed board-surface temperature. The second view is the optional thin-sheet model, using an assumed 35 W/(m·K) in-plane conductivity, 0.8 emissivity, 10 m/s forced airflow, a 48-cell long-axis grid and the saved 1.6 mm thickness. Those inputs are illustrative, not measured properties of the fixture.

The [component-results screenshot](examples/quicktherm-native-results.png) shows the sortable temperature table and summary in the same native window.

Open a saved board in KiCad PCB Editor, launch **WayriCAD QuickTherm**, map the saved footprint fields for dissipated power and thermal resistance, select the components in scope, and run. The results include top and bottom views, contours, a 3D overview, a component temperature table, and cross-selection back to the PCB Editor. Optional virtual heatsinks and board models include thin-sheet and layer-resolved copper/vertical-path approximations. The report records assumptions, coverage and heat balance where applicable. QuickTherm does not perform CFD, transient or coupled electrothermal simulation.

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
