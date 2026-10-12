# WayriCAD

[![Release](https://img.shields.io/github/v/release/wayri/WayriCAD?color=168b78)](https://github.com/wayri/WayriCAD/releases/latest)
[![CI](https://github.com/wayri/WayriCAD/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/wayri/WayriCAD/actions/workflows/ci.yml)
[![KiCad target](https://img.shields.io/badge/KiCad-10-315b7d)](docs/COMPATIBILITY.md)
[![Tools](https://img.shields.io/badge/Tools-19-168b78)](#all-19-plugins)
[![Licenses](https://img.shields.io/badge/License-GPL--3.0%20%2F%20MIT-64748b)](#acknowledgements-and-ai-disclosure)

**PCB design, analysis and project review in KiCad.** Choose from 19 independently
installable plugins. Processing runs locally after setup. KiCad 10 is the validated target.

## Start here

| What you need | Where to go |
|---|---|
| Install the tools | [Quick steps](#install-and-open) · [Installation guide](docs/INSTALLATION.md) |
| Run your first analysis | [Getting started](#getting-started) |
| Download or update | [Release 3.6.16](https://github.com/wayri/WayriCAD/releases/tag/v3.6.16) · [Release notes](docs/RELEASE_NOTES_3.6.16.md) |
| Choose a tool | [All 19 plugins](#all-19-plugins) |
| See the interfaces | [Screenshots](#plugin-previews) |
| Find detailed instructions | [Full user guide](docs/USER_GUIDE.md) |
| Resolve a problem | [Help and upgrades](#help-and-upgrades) |
| Automate or contribute | [Development](#automation-and-development) |

## Install and open

1. Open **Plugin and Content Manager** in KiCad Manager. Add this repository:

   ```text
   https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json
   ```

2. Select **WayriCAD Plugin Repository** and install the tools you want. You can
   also download a PCM ZIP from [Releases](https://github.com/wayri/WayriCAD/releases)
   and use **Install from File**, without unpacking it.
3. For IPC tools, enable the API and configure Python in **Preferences → Plugins**.
   Allow the first dependency setup to finish, then restart PCB Editor.
4. Open and save your project. Launch a tool from **Tools → External Plugins** or
   the toolbar. **WayriCAD — All tools…** searches the installed tools if the menu is crowded.

Fusion uses the native plugin loader and does not need the IPC API enabled.
First-time setup may need internet access. For setup problems or offline use,
use the [help table](#help-and-upgrades) below.

<a id="choose-a-kicad-workflow"></a>

## Getting started

| Your first task | Quick start | Detailed guide |
|---|---|---|
| Check voltage drop and copper losses | [Quick PI](#start-quick-pi) | [PI guide](quick_pi_plugin/README.md#workflow) |
| Check board and component temperatures | [QuickTherm](#start-quicktherm) | [Thermal guide](quick_therm_plugin/QUICK_THERM_USER_GUIDE.md) |
| Screen signal delay and reflections | [Quick SI](#start-quick-si) | [SI guide](signal_integrity_advisor_plugin/ReadMe.md) |
| Measure route R, L, C and impedance | [Trace RLC](#start-rlc) | [RLC guide](trace_impedance_plugin/ReadMe.md#workflow) |
| Edit and export a BOM | [BOM workflow](#start-bom) | [BOM guide](bom_studio_plugin/README.md#everyday-workflow) |
| Inspect copper and component analytics | [Analytics workflow](#start-analytics) | [Analytics guide](bom_studio_plugin/README.md) |

Save the PCB, refill its zones, and save Board Setup before analysis. Start with
one net or a small component group, then expand the study. Unknown results mean
an input or model is missing; they are not a pass.

<a id="start-quick-pi"></a>

### Quick PI — check a power path

1. Open **WayriCAD Quick PI**. In **Setup**, choose the power net, source pad and sink pad.
2. Enter **Source · V** and **Load · A**. Add sink voltage limits or **Additional sinks** if needed.
3. Click **Preview** to inspect the extracted copper, then **Run**.
4. Inspect **Results** for voltage drop, current density and losses. Choose a layer,
   hover for values, and click to pin probes. Use **Export** for HTML and JSON.

For your first run, use the default layered DC model. Review copper thickness,
via plating and mesh refinement before relying on local peaks.


<a id="start-quicktherm"></a>

### QuickTherm — check board and part temperatures

1. Open **WayriCAD QuickTherm**. In **Component inputs**, select the parts to include
   and enter their actual operating power, not their maximum power rating.
2. Use **Field mapping…** for your property names. Add the thermal resistances and
   temperature limits needed by the selected model; missing junction paths stay unknown.
3. In **Board + results**, review the board heat model, materials, ambient temperature
   and environment. Start with a steady-state study and click **Run thermal**.
4. Use **Top**, **Bottom** or **3D**, probe the board and select parts in the temperature
   table. Export the report. Add transient power steps after reviewing the steady result.

QuickTherm installs separately from Quick PI. Air, vacuum and other environments
need explicit heat-rejection paths; airflow fields are not solved.


<a id="start-quick-si"></a>

### Quick SI — screen a routed signal

1. Open **WayriCAD Quick SI**. Search for a net or use **Select net on board**.
2. Choose source and receiver pads. Review the saved physical stackup and the
   driver/load assumptions, including rise time and resistance.
3. Click **Screen selected path**. Inspect delay, routed sections, impedance coverage
   and reflection estimates; unresolved sections remain visible.
4. Inspect the route and waveform plots, then export HTML/JSON for review.

Automatic timing assumes ideal continuous references where indicated. A mixed
route may have usable section results without a single overall impedance.


<a id="start-rlc"></a>

### Trace RLC — measure a routed connection

1. Open **Trace RLC / Impedance**, choose the net and two different pads.
2. Select **Path** for connected traces/vias/zones, or **Zone/plane** for a filled
   island with a declared current-corridor width. Use **Auto** reference or select a layer.
3. Run **Analyze**, then inspect the copper preview and per-section R, L, C and impedance.
4. Export the results. Use **Line cross section** for manually entered supported CPW,
   grounded CPW or coupled-stripline geometries.

Automatic board impedance covers supported single-ended microstrip/stripline
sections. Differential-pair mode measures paths/skew; it does not automatically
extract coupled differential impedance.

<a id="start-bom"></a>

### BOM Studio workflow — now in Analytics Studio

1. Open **WayriCAD Analytics Studio** from your saved project.
2. In **BOM settings**, choose fields, grouping, sorting and DNP filters.
3. Edit fields in **BOM workspace**, then save the workspace sidecar.
4. Use **Exports & templates** to preview and export a BOM. Use **Review & native sync**
   only when you want reviewed edits written back to the saved KiCad project.

**BOM Studio was renamed Analytics Studio; they are one plugin.** Existing package
IDs and workspace files are retained. Native KiCad exports read saved source;
workspace exports can include staged edits.

<a id="start-analytics"></a>

### Analytics Studio — inspect components and copper

1. Open **Board, copper & components** in Analytics Studio.
2. Review mapped cost, mass and power fields for component analytics.
3. Open **Board & copper** for board area, layer coverage, net/zone copper areas,
   track lengths, via counts and per-component pad-contact areas.
4. Search by net or part, inspect unknowns, and export the tables as CSV, XLSX, JSON or HTML.

Board analytics uses saved geometry and saved zone fills. Pad-contact area means
nominal copper land area, not thermal conductance. Missing values and mixed
currencies stay explicit.

<a id="all-16-plugins"></a>
<a id="all-18-plugins"></a>

## All 19 plugins

The IPC packages are **3.6.16**; Fusion is **0.9.8**, and Variant Manager is **0.6.1**.
Select a plugin for its full guide and supported models.

| Plugin | Use it for |
|---|---|
| <img src="quick_pi_plugin/icon.png" width="24" height="24" alt="Quick PI icon"> [Quick PI](quick_pi_plugin/README.md) | Voltage drop, current flow and copper losses. |
| <img src="quick_therm_plugin/icon.png" width="24" height="24" alt="QuickTherm icon"> [QuickTherm](quick_therm_plugin/README.md) | Board and component temperatures, heating playback and thermal reports. |
| <img src="signal_integrity_advisor_plugin/icon.png" width="24" height="24" alt="Quick SI icon"> [Quick SI](signal_integrity_advisor_plugin/ReadMe.md) | Signal delay, reflections, termination and return-path screening. |
| <img src="trace_impedance_plugin/icon.png" width="24" height="24" alt="Trace RLC / Impedance icon"> [Trace RLC / Impedance](trace_impedance_plugin/ReadMe.md) | Route resistance, inductance, capacitance and supported impedance estimates. |
| <img src="bom_studio_plugin/icon.png" width="24" height="24" alt="Analytics Studio icon"> [Analytics Studio](bom_studio_plugin/README.md) | BOM editing, purchasing tables and board/copper analytics. |
| <img src="protocol_constraint_composer_plugin/icon.png" width="24" height="24" alt="Constraint Studio icon"> [Constraint Studio](protocol_constraint_composer_plugin/ReadMe.md) | Design rules, netclasses and per-layer routing profiles. |
| <img src="project_fusion_plugin/icon.png" width="24" height="24" alt="Project Fusion icon"> [Project Fusion](project_fusion_plugin/README.md) | Combine projects or circuit blocks and review linked updates. |
| <img src="variant_manager_plugin/icon.png" width="24" height="24" alt="Variant Manager icon"> [Variant Manager](variant_manager_plugin/README.md) | Compare, edit, merge and recover assembly variants. |
| <img src="embed_3d_plugin/icon.png" width="24" height="24" alt="Embed3D icon"> [Embed3D](embed_3d_plugin/README.md) | Collect libraries and 3D models for portable projects. |
| <img src="fanout_generator_plugin/icon.png" width="24" height="24" alt="Fanout Generator icon"> [Fanout Generator](fanout_generator_plugin/ReadMe.md) | Preview and place escape tracks and vias. |
| <img src="via_stitching_plugin/icon.png" width="24" height="24" alt="Via Stitching icon"> [Via Stitching](via_stitching_plugin/ReadMe.md) | Add reviewed, net-connected stitching vias. |
| <img src="bulk_label_editor_plugin/icon.png" width="24" height="24" alt="Bulk Label Editor icon"> [Bulk Label Editor](bulk_label_editor_plugin/ReadMe.md) | Rename references, fields and PCB text in bulk. |
| <img src="extract_pins_plugin/icon.png" width="24" height="24" alt="Pin Extractor icon"> [Pin Extractor](extract_pins_plugin/ReadMe.md) | Export pin tables, connector diagrams and signal maps. |
| <img src="harness_workbench_plugin/icon.png" width="24" height="24" alt="Harness Workbench icon"> [Harness Workbench](harness_workbench_plugin/ReadMe.md) | Map connectors, cables, bundles and wire requirements. |
| <img src="copper_balancer_plugin/icon.png" width="24" height="24" alt="Copper Balancer icon"> [Copper Balancer](copper_balancer_plugin/README.md) | Add isolated copper patterns for more even copper density. |
| <img src="mechanical_check_plugin/icon.png" width="24" height="24" alt="Mechanical Check icon"> [Mechanical Check](mechanical_check_plugin/README.md) | Inspect 3D collisions, clearances and board assemblies. |
| <img src="heater_designer_plugin/icon.png" width="24" height="24" alt="Heater Designer icon"> [Heater Designer](heater_designer_plugin/ReadMe.md) | Design and preview PCB or foil heating patterns. |
| <img src="planar_magnetics_plugin/icon.png" width="24" height="24" alt="Planar Magnetics icon"> [Planar Magnetics](planar_magnetics_plugin/ReadMe.md) | Design PCB coils and screen magnetic/actuator behavior. |
| <img src="manufacturing_readiness_plugin/icon.png" width="24" height="24" alt="Manufacturing Readiness icon"> [Manufacturing Readiness](manufacturing_readiness_plugin/ReadMe.md) | Check fabrication constraints and prepare manufacturing outputs. |

## Plugin previews

<a id="latest-gui-snapshots"></a>
<a id="more-plugin-previews"></a>

Current and earlier screenshots are grouped by tool. Click an image for its
original resolution. Demonstration inputs are not predictions for your board;
older captures retain generic-path redactions. [Capture provenance](docs/audits/README_GALLERY.md).

### [Quick PI](quick_pi_plugin/README.md)

**Board and results workspace**

<a href="quick_pi_plugin/help-workspace.png"><img src="quick_pi_plugin/help-workspace.png" width="960" alt="Native Quick PI board and result workspace"></a>

The displayed field solves a uniform copper plate; the routed PCB provides visual context. [Capture and reference](docs/audits/QUICK_PI_WORKSPACE.md).

**Package contacts and copper losses · 3.6.14**

<a href="docs/assets/package-conduction/quick-pi.png"><img src="docs/assets/package-conduction/quick-pi.png" width="960" alt="Quick PI with explicit package contacts and separately reported contact Joule losses"></a>

Generated demonstration board with illustrative lead/solder properties. [Capture inputs](docs/assets/package-conduction/PROVENANCE.md) · [Contact model](docs/PACKAGE_CONDUCTION.md).

**Research and model references**

| Reference | Role |
|---|---|
| [MIT conduction chapter](https://ocw.mit.edu/courses/res-6-002-electromagnetic-field-theory-a-problem-solving-approach-spring-2008/2cccce322d387cccbc78c3ed65843f49_MITRES_6_002S08_chp03_text.pdf) | Analytical resistance checks. |
| [Elmer beam fixture](https://github.com/ElmerCSC/elmerfem/tree/b461e4be77d0ca13bada61f04819fccb20a524ab/fem/tests/ConstantUnknownPotStatCurrent) | Published numerical benchmark inputs. |
| [Full references](quick_pi_plugin/README.md#references-and-research) | Meshing paper, verification guidance and model limits. |


### [QuickTherm](quick_therm_plugin/README.md)

**STEP models and transient heating**

<a href="quick_therm_plugin/examples/quicktherm-component-heating.png"><img src="quick_therm_plugin/examples/quicktherm-component-heating.png" width="960" alt="QuickTherm component heating and board results"></a>

Calculated board and declared component RC temperatures; each modeled part has one temperature, and grey parts remain unknown. [Inputs and validation](docs/audits/QUICKTHERM_COMPONENT_HEATING.md).

**Component inputs**

<a href="quick_therm_plugin/examples/quicktherm-input-workspace.png"><img src="quick_therm_plugin/examples/quicktherm-input-workspace.png" width="960" alt="QuickTherm full-width editable component table with scanned power and Rtheta JA, JB and JC values, temperature limits and select-all controls"></a>

Review power, thermal resistances, limits and analysis scope. [Capture notes](docs/audits/QUICKTHERM_WORKSPACE.md#screenshot-provenance).

**Imported copper/contact heat and fitted controls · 3.6.14**

<a href="docs/assets/package-conduction/quick-therm.png"><img src="docs/assets/package-conduction/quick-therm.png" width="960" alt="QuickTherm transient board field with numeric inputs and controls fitting the sidebar"></a>

The illustrative 1 s frame includes imported copper and contact losses. [Capture inputs](docs/assets/package-conduction/PROVENANCE.md) · [Validation](docs/audits/PACKAGE_CONDUCTION.md).

**Research and model references**

| Reference | Role |
|---|---|
| [Gmsh research paper (2009)](https://gmsh.info/doc/preprints/gmsh_paper_preprint.pdf) | Optional 3D mesher provenance. |
| [CalculiX manual](https://www.dhondt.de/ccx_2.22.pdf) | Thermal backend input format. |
| [Full references](quick_therm_plugin/README.md#references-and-research) | Package-model context, bridge and limitations. |


### [Quick SI](signal_integrity_advisor_plugin/ReadMe.md)

**Routed signal analysis**

<a href="signal_integrity_advisor_plugin/help-workflow.png"><img src="signal_integrity_advisor_plugin/help-workflow.png" width="960" alt="Quick SI routed signal analysis"></a>

Inspect the selected signal path and its available results.

**Protocol screening**

<a href="signal_integrity_advisor_plugin/help-protocols.png"><img src="signal_integrity_advisor_plugin/help-protocols.png" width="960" alt="Quick SI native window preview"></a>

Missing models and reference coverage remain visible.

**Research and model references**

| Reference | Role |
|---|---|
| [TI high-speed layout guidance](https://www.ti.com/lit/an/slla414/slla414.pdf) | Protocol/routing context. |
| [Nubis SignalIntegrity](https://github.com/Nubis-Communications/SignalIntegrity) | Optional network interoperability. |
| [Full references](signal_integrity_advisor_plugin/ReadMe.md#references-and-research) | I2C/CAN/DDR sources and shared impedance model. |


### [Trace RLC / Impedance](trace_impedance_plugin/ReadMe.md)

**Saved-board route analysis**

<a href="trace_impedance_plugin/help-marble-path.png"><img src="trace_impedance_plugin/help-marble-path.png" width="960" alt="Trace RLC saved-board route analysis"></a>

Inspect connected copper and per-section electrical coverage.

**AC and geometry analysis**

<a href="trace_impedance_plugin/help-ac-geometry.png"><img src="trace_impedance_plugin/help-ac-geometry.png" width="960" alt="Trace RLC native window preview"></a>

Review the route geometry and conductor-loss estimates.

**Research and model references**

| Reference | Role |
|---|---|
| [Pinned EMerge equations](https://github.com/wayri/EMerge/blob/50283a2/src/emerge/_emerge/geo/pcb_tools/calculator.py) | Scalar cross-section source. |
| [Qucs CPW theory](https://qucs.github.io/tech/node86.html) | Conformal-mapping equation reference. |
| [Full references](trace_impedance_plugin/ReadMe.md#references-and-research) | Microstrip paper, via/plane sources and validation fixtures. |


### [Analytics Studio](bom_studio_plugin/README.md)

**Board and copper analytics**

<a href="bom_studio_plugin/help-board-copper.png"><img src="bom_studio_plugin/help-board-copper.png" width="960" alt="Analytics Studio board and copper tables"></a>

Inspect layer/net areas, zones, vias and component pad-contact tables.

**Component cost, mass and power · earlier BOM Studio interface**

<a href="bom_studio_plugin/help-cost-mass.png"><img src="bom_studio_plugin/help-cost-mass.png" width="960" alt="Analytics Studio native window preview"></a>

The earlier BOM Studio view is retained here under its current name, Analytics Studio. Missing component data stays explicit.

### [Constraint Studio](protocol_constraint_composer_plugin/ReadMe.md)

**Rule worksheet**

<a href="protocol_constraint_composer_plugin/help-workflow.png"><img src="protocol_constraint_composer_plugin/help-workflow.png" width="960" alt="Constraint Studio with optional panels closed"></a>

Shipped UI rendered from a demonstration snapshot. Supporting panels open on demand; scope colours are condition matches, not native DRC results.

### [Mechanical Check](mechanical_check_plugin/README.md)

**3D measurements and height checks**

<a href="mechanical_check_plugin/help-workflow.png"><img src="mechanical_check_plugin/help-workflow.png" width="960" alt="Mechanical Check native STEP board workspace with an edge-to-edge ruler, global height violation markers and a compact findings sidebar"></a>

The fixture deliberately includes height violations and incomplete coverage. [Capture and validation](docs/audits/MECHANICAL_INSPECTION.md).

### [Fanout Generator](fanout_generator_plugin/ReadMe.md)

**Adaptive fanout**

<a href="fanout_generator_plugin/help-adaptive.png"><img src="fanout_generator_plugin/help-adaptive.png" width="960" alt="Adaptive fanout native window preview"></a>

Review pads, existing copper and proposed tracks/vias before applying.

### [Planar Magnetics](planar_magnetics_plugin/ReadMe.md)

**Motor EMF and winding analysis**

<a href="planar_magnetics_plugin/help-motor-emf.png"><img src="planar_magnetics_plugin/help-motor-emf.png" width="960" alt="Magnetics native window preview"></a>

Review winding layouts, motor EMF/force and supported simulation models in the guide.

**Research and model references**

| Reference | Role |
|---|---|
| [Reviewed motor research](docs/MOTOR_MODELS.md#research-reviewed) | Published work and implemented/future model distinctions. |
| [Magnetics equation references](docs/MAGNETICS_VERIFICATION.md) | Filament and capacitance-matrix checks. |


### [Variant Manager](variant_manager_plugin/README.md)

**Assembly comparison**

<a href="variant_manager_plugin/help-workspace.png"><img src="variant_manager_plugin/help-workspace.png" width="960" alt="Variant Manager native assembly comparison"></a>

Compare saved and staged assembly states, with bulk operations and reviewed recovery.

## Help and upgrades

| Topic | Guide |
|---|---|
| Missing actions, runtimes or installation paths | [Troubleshooting](docs/TROUBLESHOOTING.md) |
| Dependencies and offline use | [Runtime setup](wayricad_runtime/RUNTIME_SETUP.md) |
| Tested hosts and known limits | [Compatibility](docs/COMPATIBILITY.md) |
| What plots, probes and analysis models represent | [Analysis interactions](docs/ANALYSIS_INTERACTIONS.md) |
| Command-line use | [CLI guide](docs/CLI_USER_GUIDE.md) |
| Repeatable reports and KiCad jobsets | [Jobsets](wayricad_runtime/JOBSETS.md) |

<a id="upgrade-safely"></a>

Refresh PCM, install updates and restart PCB Editor. Keep project backups and BOM
workspace files. Remove retired standalone tools to avoid duplicate actions:
PDN Decoupling is in Quick PI; Return-Path Auditor and Test Point Descriptor are
in Quick SI; Embed3D combines Localizer and Portable Assets.

<a id="recommended-system"></a>

Hardware planning details are in [System requirements](docs/SYSTEM_REQUIREMENTS.md).

## Automation and development

Use `wayricad jobs` for repeatable analysis/report sequences and KiCad jobsets.

| Developer topic | Reference |
|---|---|
| Contribution and validation requirements | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Repository structure and working conventions | [AGENTS.md](AGENTS.md) |
| GUI dependencies and offline runtime setup | [Runtime setup](wayricad_runtime/RUNTIME_SETUP.md) |

```text
python -m pip install -e ".[test]"
python -m pytest tests -q
python build_pcm.py --output-dir .validation/candidate-pcm
python tools/validate_packages.py --archive-dir .validation/candidate-pcm
```

Each plugin also has its own tests. Skipped checks do not establish native GUI
compatibility. Validation records are in [the release audit](docs/audits/RELEASE_3.6.16.md).

## Acknowledgements and AI disclosure

WayriCAD uses AI assistance for development, research and documentation;
maintainers remain responsible for validation and releases.

| Project information | Reference |
|---|---|
| Maintainer | [Wayri (Yawar)](https://github.com/wayri) |
| WayriCAD license | [GPL-3.0](LICENSE) |
| Fusion and Variant Manager | MIT licensed; see each package's license |
| Credits and AI assistance | [Acknowledgements](ACKNOWLEDGEMENTS.md) |
