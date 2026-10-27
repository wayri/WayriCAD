# WayriCAD

[![Release](https://img.shields.io/github/v/release/wayri/WayriCAD?color=168b78)](https://github.com/wayri/WayriCAD/releases/latest)
[![CI](https://github.com/wayri/WayriCAD/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/wayri/WayriCAD/actions/workflows/ci.yml)
[![KiCad target](https://img.shields.io/badge/KiCad-10-315b7d)](docs/COMPATIBILITY.md)
[![Tools](https://img.shields.io/badge/Tools-24-168b78)](#all-24-plugins)
[![Licenses](https://img.shields.io/badge/License-GPL--3.0%20%2F%20MIT-64748b)](#acknowledgements-and-ai-disclosure)

**PCB design, analysis and project review in KiCad.** Choose from 24 independently
installable plugins in the source catalogue. Processing runs locally after setup. KiCad 10 is the validated target.

**New in 3.6.38:** Quick PI recommends same-net connector/IC pin groups,
solves constant-power loads, and reviews parallel components in series paths.
Transient, AC and PDN setup is easier, with fresh native screenshots and help.
[Release notes](docs/RELEASE_NOTES_3.6.38.md).

**In development — guided SI and thermal studies:** configure endpoint roles and
line assumptions together, review heating in watts, and inspect exact transient
samples. [Changes and validation](docs/RELEASE_NOTES_3.6.39.md).

## Start here

| What you need | Where to go |
|---|---|
| Install the tools | [Quick steps](#install-and-open) · [Installation guide](docs/INSTALLATION.md) |
| Run your first analysis | [Getting started](#getting-started) |
| Download or update | [Release 3.6.38](https://github.com/wayri/WayriCAD/releases/tag/v3.6.38) · [Release notes](docs/RELEASE_NOTES_3.6.38.md) |
| Place silkscreen labels | [Silkscreen Label Placer](silkscreen_label_plugin/README.md) · [Quick start](#start-silkscreen) |
| Choose a tool | [All 24 plugins](#all-24-plugins) |
| See the interfaces | [Showcase](#showcase) · [Screenshots by plugin](#plugin-previews) |
| Find detailed instructions | [Full user guide](docs/USER_GUIDE.md) |
| Review algorithms and research | [Methods, sources and verification by tool](docs/METHODS_AND_RESEARCH.md) |
| Resolve a problem | [Help and upgrades](#help-and-upgrades) |
| Automate or contribute | [Development](#automation-and-development) |

## Showcase

Click a screenshot for its full resolution. [More screenshots, grouped by plugin](#plugin-previews).

| [Quick PI — Marble board preview](#quick-pi) | [QuickTherm — 3D temperature view](#quicktherm) |
|---|---|
| <a href="quick_pi_plugin/help-marble-geometry-3.6.28.png"><img src="quick_pi_plugin/help-marble-geometry-3.6.28.png" width="460" alt="Quick PI showing extracted copper on public Marble"></a> | <a href="quick_therm_plugin/examples/quicktherm-3d-3.6.38.png"><img src="quick_therm_plugin/examples/quicktherm-3d-3.6.38.png" width="460" alt="QuickTherm native 3D temperature surface on the thermal demonstration board"></a> |
| Geometry preview; no PI field solved. | Assumed-load demonstration; STEP models disabled. |
| **[Trace Refiner — old/new comparison](#trace-refiner)** | **[Fanout — connector escape preview](#fanout-generator)** |
| <a href="trace_refiner_plugin/help-validated-comparison.png"><img src="trace_refiner_plugin/help-validated-comparison.png" width="460" alt="Trace Refiner comparing amber original tracks with teal proposed tracks"></a> | <a href="fanout_generator_plugin/help-connector-proposed.png"><img src="fanout_generator_plugin/help-connector-proposed.png" width="460" alt="Fanout Generator previewing six escapes on a synthetic connector fixture"></a> |
| Synthetic fixture; native validation reported no new DRC findings. | Six-pin synthetic fixture; [dense Marble trial results](docs/audits/FANOUT_REAL_BOARD_TRIALS_2026-10-23.md). |

## Latest release — 3.6.33

Refresh the WayriCAD repository in Plugin and Content Manager, install updates, then restart PCB Editor.

| Improvement | Workflow |
|---|---|
| Computed thermal playback | Default 0.1 s frames, separate solver/output intervals, Previous/Next and playback speed controls. [QuickTherm guide](quick_therm_plugin/README.md). |
| Reviewed IBIS circuits | Load exact source/receiver models, export selected complete routes and copy a native KiCad circuit. [SI workflow and limits](signal_integrity_advisor_plugin/ReadMe.md#reviewed-ibis-circuit-export). |
| PI melting and bottlenecks | Trace-cell and via-barrel adiabatic melting estimates, limiting-region selection and heat maps. Melting does not establish fuse opening. [PI guide](quick_pi_plugin/README.md). |
| SI neighbour map | Search nearby traces, inspect gap/parallel overlap and review supported local coupling separately from geometric exposure. [SI guide](signal_integrity_advisor_plugin/ReadMe.md). |
| Live Quick PI current | Ctrl+scroll over a sink pad changes that load; other solved copper adjusts total demand. Scroll zooms. A cursor readout compares before/after values. [Controls and model limits](quick_pi_plugin/README.md#individual-sink-current-wheel-control). |
| Dense-board Fanout | Native padstack/track/arc checks, real keepout polygons, faster connector exits and retained short-stub continuation. [Marble results](docs/audits/FANOUT_DENSE_BOARD_FIXES_2026-10-23.md). |
| Simpler Constraint Studio | Ordinary rules and netclasses stay in KiCad; Studio retains a read-only overview, protocol presets, matrices, reusable sets and reviewed export. [Guide](protocol_constraint_composer_plugin/ReadMe.md). |
| Fanout corrections | Accept nullable saved netclass assignments and reject duplicate Fixed-mode launches on connected pads. [Real-board trial results and remaining limits](docs/audits/FANOUT_REAL_BOARD_TRIALS_2026-10-23.md). |
| Updated guides and showcase | Refreshed navigation for all 24 plugins, retained earlier previews and added current native screenshots. |
| Guard via stitching | Fence selected signal nets/traces on a distinct guard net; review pitch, offset, clearances and rejections. [Guide](via_stitching_plugin/ReadMe.md). |
| Guided, cancellable Fanout | Actual component thumbnails, Before/After and small-window actions. [Guide](fanout_generator_plugin/ReadMe.md). |
| Shared responsiveness | Faster dropdowns and exact picking; Quick PI geometry-ready time 33.09 s to 20.26 s. [Measurements and limits](docs/audits/SUITE_RESPONSIVENESS_2026-10-23.md). |
| Assistant — testing | Local fuzzy command planning, clarification and reports across registered CLI actions. [Guide](suite_assistant_plugin/README.md). |
| Faster fresh PI solves | Reuse one native PCB across a multi-net batch and reduce geometry/matrix overhead. Marble cold median 43.24 s to 31.71 s. [Measurements](docs/audits/QUICK_PI_COLD_PERFORMANCE_2026-10-22.md). |
| Responsive native board view | Saved silkscreen retains its physical size and placement. Marble full viewport redraw 763 ms to 58 ms; cached drag and indexed probes reduce interaction work. [Measurements](docs/audits/QUICK_PI_VIEWPORT_PERFORMANCE_2026-10-23.md). |
| Live, faster fanout preview | Selection and style changes update the main canvas and a component thumbnail. Fixed Marble U35 planning 21.94 s to 0.29 s with identical plans. [Fanout guide](fanout_generator_plugin/ReadMe.md). |
| Faster Quick PI interaction | Reuse unchanged results, load selected-net display geometry in the worker, and retain plot artists during navigation. [Measurements](docs/audits/QUICK_TOOLS_PERFORMANCE.md). |
| Better net selection and views | Search with wildcards or fuzzy suggestions without losing the selected net. Focus maps and PCB selection on the simulated nets; choose a combined-layer projection. |
| Clear trace comparisons | Trace Refiner 0.3.1 fixes missing UUID-setter compatibility and provides amber/teal Overlay, Before, After and Side-by-side views. |
| Pad/via endpoint centering | Run the separate Trace Refiner action for pad/via endpoint centering. [Trace Refiner guide](trace_refiner_plugin/README.md). |
| Readable local silkscreen | Preserve acceptable references; try footprint-axis placement, bounded sizing and local repacking near the owning courtyard. Every eligible reference receives an outcome. [Silkscreen guide](silkscreen_label_plugin/README.md). |
| Managed silkscreen guides | Leaders default off. Optional short straight guides have persistent ownership, detached-guide auditing and reversible cleanup. CLI HTML reports show both board faces. [Silkscreen guide](silkscreen_label_plugin/README.md). |
| Shared-return PI and multi-pad units | Solve common return copper across rails; choose multiple physical source/load pads per unit. Shared return losses count once. [PI guide](quick_pi_plugin/README.md). |
| Automatic mesh sizing | PI and thermal models recommend sizes and refine supported regions locally, with manual overrides and explicit budget warnings. |
| Power and thermal Sankeys | Follow source-to-load power or individual-part dissipation in native actions and offline HTML reports. |
| PI Joule heating checkbox | Enable temperature feedback, then supply reviewed material and cooling inputs. Plain DC already reports copper losses. |
| Quick SI local crosstalk | Configure directed aggressor/victim pairs and review supported straight-section coupling, modeled coverage and omitted geometry. [SI guide](signal_integrity_advisor_plugin/ReadMe.md). |
| PI / SI / Therm reports | Read status, coverage and provenance; search/sort tables, navigate sections and print. Interactive plots and probes remain available. |
| CLI access across all 24 tools | `wayricad tools list`, `doctor` and `run TOOL -- --help`; includes reviewed analysis jobsets. [Command catalogue](docs/TOOL_CLI_CATALOGUE.md). |
| Mechanical Check review | Hideable findings panel, clearer details, direct focus/isolation and separate measurement tools. [Mechanical guide](mechanical_check_plugin/README.md). |

PI shared returns are fixed-current, fixed-temperature DC models. SI coupling remains a local supported-section screen; it is not a whole-board channel prediction. Automatic geometry sizing is not convergence proof, and 3D sizing stays manual. [Release notes](docs/RELEASE_NOTES_3.6.38.md).

See [screenshots grouped by plugin](#plugin-previews), [offline help for all tools](docs/HELP_INDEX.md), and [panel/table controls](docs/UI_ACCESSIBILITY.md).

### Analysis evidence

This release includes jointly solved shared-return copper for multi-net PI,
multiple source/load pads per PI unit, and local coupled-line crosstalk analysis
for SI. Read the
[Marble validation results and model limits](docs/audits/MARBLE_COUPLED_ANALYSIS.md),
[PI guide](quick_pi_plugin/README.md) and
[SI guide](signal_integrity_advisor_plugin/ReadMe.md) before interpreting them
as whole-board predictions.

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

Fusion, Variant Manager, Silkscreen Label Placer, Trace Refiner, Component Arranger and Layer Counter use the native plugin loader and do not need the IPC API enabled.
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
| Arrange silkscreen labels | [Label placement](#start-silkscreen) | [Silkscreen guide](silkscreen_label_plugin/README.md) |

Save the PCB, refill its zones, and save Board Setup before analysis. Start with
one net or a small component group, then expand the study. Unknown results mean
an input or model is missing; they are not a pass.

<a id="start-silkscreen"></a>

### Silkscreen Label Placer — arrange readable labels

1. Install **Silkscreen Label Placer** from the WayriCAD package feed, or download its [0.3.3 PCM ZIP](https://github.com/wayri/WayriCAD/releases/download/v3.6.24/WayriCAD-silkscreen-label-0.3.3-PCM.zip) and use **Install from File**. Restart PCB Editor.
2. Open **WayriCAD Silkscreen Label Placer** and choose all eligible labels, problem-only correction or selected parts. Leave **References only (R1, C1…)** selected to preserve values and manual text. Acceptable labels are preserved and leaders are off by default.
3. Under **Options**, enable automatic sizing and set a minimum height if needed. Choose allowed orientations and reading directions. Add editable bold, italic or knockout rules for test points and connectors.
4. Click **Preview**, inspect both board sides and unresolved labels, then **Apply labels**. Run KiCad DRC before saving. Labels that cannot fit safely stay unchanged.

[User guide and formatting examples](silkscreen_label_plugin/README.md) · [Release](https://github.com/wayri/WayriCAD/releases/tag/v3.6.24)

<a id="start-quick-pi"></a>

### Quick PI — check a power path

1. Open **WayriCAD Quick PI**. In **Setup**, choose the power net, source pad and sink pad.
2. Enter **Source · V** and **Load · A**. Add sink voltage limits or **Additional sinks** if needed.
3. Leave **Automatic mesh** enabled for geometry-based sizing, or turn it off to
   enter a manual mesh edge. Click **Preview** to inspect the copper, then **Run**.
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
   and environment. Use **Automatic mesh** for supported board models, then start
   with a steady-state study and click **Run thermal**.
4. Use **Top**, **Bottom** or **3D**, probe the board and select parts in the temperature
   table. Export the report. For time-varying heating, open **Heating study…** to
   review duration, solver/frame intervals and storage advice, then edit power
   steps directly in watts.

QuickTherm installs separately from Quick PI. Air, vacuum and other environments
need explicit heat-rejection paths; airflow fields are not solved.

Automatic sizing refines supported regions near sources and contacts within
the mesh budget. It is a starting recommendation, not proof of convergence.
Review the selected sizes and unresolved-feature warnings in the report;
compare finer meshes before trusting a local peak. Manual sizing remains
available, including for backends without automatic sizing.


<a id="start-quick-si"></a>

### Quick SI — screen a routed signal

1. Open **WayriCAD Quick SI**. Search for a net or use **Select net on board**.
2. Open **Set up path and response…** to choose source and receiver pads and
   review rise time, impedance, dielectric and driver/load assumptions together.
   Confirm the actual return in the main workspace; other same-part pads are
   shown for review and are not shorted into an SI endpoint.
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

<a id="all-20-plugins"></a>

<a id="all-21-plugins"></a>

## All 24 plugins

All 24 plugins are available in release **3.6.33**. Assistant is marked **testing**;
individual package versions and runtime requirements are in their guides.
Select a plugin for its full guide and supported models.

| Plugin | Use it for |
|---|---|
| <img src="suite_assistant_plugin/icon.png" width="24" height="24" alt="WayriCAD Assistant icon"> [WayriCAD Assistant](suite_assistant_plugin/README.md) | Plain-English tool selection, visual context and reviewed command execution (testing). |
| <img src="quick_pi_plugin/icon.png" width="24" height="24" alt="Quick PI icon"> [Quick PI](quick_pi_plugin/README.md) | Voltage drop, current flow and copper losses. |
| <img src="quick_therm_plugin/icon.png" width="24" height="24" alt="QuickTherm icon"> [QuickTherm](quick_therm_plugin/README.md) | Board and component temperatures, heating playback and thermal reports. |
| <img src="signal_integrity_advisor_plugin/icon.png" width="24" height="24" alt="Quick SI icon"> [Quick SI](signal_integrity_advisor_plugin/ReadMe.md) | Signal delay, reflections, termination and return-path screening. |
| <img src="trace_impedance_plugin/icon.png" width="24" height="24" alt="Trace RLC / Impedance icon"> [Trace RLC / Impedance](trace_impedance_plugin/ReadMe.md) | Route resistance, inductance, capacitance and supported impedance estimates. |
| <img src="bom_studio_plugin/icon.png" width="24" height="24" alt="Analytics Studio icon"> [Analytics Studio](bom_studio_plugin/README.md) | BOM editing, purchasing tables and board/copper analytics. |
| <img src="protocol_constraint_composer_plugin/icon.png" width="24" height="24" alt="Constraint Studio icon"> [Constraint Studio](protocol_constraint_composer_plugin/ReadMe.md) | Protocol presets, clearance matrices, scoped layer profiles and reviewed export. |
| <img src="project_fusion_plugin/icon.png" width="24" height="24" alt="Project Fusion icon"> [Project Fusion](project_fusion_plugin/README.md) | Combine projects or circuit blocks and review linked updates. |
| <img src="variant_manager_plugin/icon.png" width="24" height="24" alt="Variant Manager icon"> [Variant Manager](variant_manager_plugin/README.md) | Compare, edit, merge and recover assembly variants. |
| <img src="embed_3d_plugin/icon.png" width="24" height="24" alt="Embed3D icon"> [Embed3D](embed_3d_plugin/README.md) | Collect libraries and 3D models for portable projects. |
| <img src="fanout_generator_plugin/icon.png" width="24" height="24" alt="Fanout Generator icon"> [Fanout Generator](fanout_generator_plugin/ReadMe.md) | Preview and place escape tracks and vias. |
| <img src="via_stitching_plugin/icon.png" width="24" height="24" alt="Via Stitching icon"> [Via Stitching](via_stitching_plugin/ReadMe.md) | Add reviewed, net-connected stitching vias. |
| <img src="trace_refiner_plugin/icon.png" width="24" height="24" alt="Trace Refiner icon"> [Trace Refiner](trace_refiner_plugin/README.md) | Review routing jog cleanup with metrics, focused proposals and exclusions; native connectivity and DRC gate Apply. |
| <img src="silkscreen_label_plugin/icon.png" width="24" height="24" alt="Silkscreen Label Placer icon"> [Silkscreen Label Placer](silkscreen_label_plugin/README.md) | Arrange labels with bounded sizing, footprint-axis placement, formatting rules and exceptional short guides. |
| <img src="component_arranger_plugin/icon.png" width="24" height="24" alt="Component Arranger icon"> [Component Arranger](component_arranger_plugin/README.md) | Preview compact anchored group placement, side/rotation/density choices and capacitor order; native validation gates Apply. |
| <img src="layer_counter_plugin/icon.png" width="24" height="24" alt="Layer Counter icon"> [Layer Counter](layer_counter_plugin/README.md) | Movable copper L1/L2 markers with zone keepouts, 24 styles and explicit mirrored/overlapping core pairs. |
| <img src="bulk_label_editor_plugin/icon.png" width="24" height="24" alt="Bulk Label Editor icon"> [Bulk Label Editor](bulk_label_editor_plugin/ReadMe.md) | Browse/search PCB nets and connections; review bulk reference, field and PCB-text edits. |
| <img src="extract_pins_plugin/icon.png" width="24" height="24" alt="Pin Extractor icon"> [Pin Extractor](extract_pins_plugin/ReadMe.md) | Export pin tables, connector diagrams and signal maps. |
| <img src="harness_workbench_plugin/icon.png" width="24" height="24" alt="Harness Workbench icon"> [Harness Workbench](harness_workbench_plugin/ReadMe.md) | Map connectors, cables, bundles and wire requirements. |
| <img src="copper_balancer_plugin/icon.png" width="24" height="24" alt="Copper Balancer icon"> [Copper Balancer](copper_balancer_plugin/README.md) | Add isolated copper patterns for more even copper density. |
| <img src="mechanical_check_plugin/icon.png" width="24" height="24" alt="Mechanical Check icon"> [Mechanical Check](mechanical_check_plugin/README.md) | Inspect 3D collisions, clearances and board assemblies. |
| <img src="heater_designer_plugin/icon.png" width="24" height="24" alt="Heater Designer icon"> [Heater Designer](heater_designer_plugin/ReadMe.md) | Design and preview PCB or foil heating patterns. |
| <img src="planar_magnetics_plugin/icon.png" width="24" height="24" alt="Planar Magnetics icon"> [Planar Magnetics](planar_magnetics_plugin/ReadMe.md) | Design PCB coils and screen magnetic/actuator behavior. |
| <img src="manufacturing_readiness_plugin/icon.png" width="24" height="24" alt="Manufacturing Readiness icon"> [Manufacturing Readiness](manufacturing_readiness_plugin/ReadMe.md) | Check fabrication constraints and prepare manufacturing outputs. |

[Silkscreen Label Placer](silkscreen_label_plugin/README.md) is available as an independent native KiCad 10 plugin in the WayriCAD package feed, with its own icon, automatic sizing and formatting rules. See its [installation guide](silkscreen_label_plugin/README.md#install-and-limits).

## Plugin previews

<a id="latest-gui-snapshots"></a>
<a id="more-plugin-previews"></a>

Current and earlier screenshots are grouped by tool. Click an image for its
original resolution. Demonstration inputs are not predictions for your board;
older captures retain generic-path redactions. [Current captures and inputs](docs/audits/QUICK_TOOL_VISUALS_3.6.38.md) · [Earlier capture provenance](docs/audits/README_GALLERY.md).

| Explore | Previews |
|---|---|
| Run analyses | [Quick PI](#quick-pi) · [QuickTherm](#quicktherm) · [Quick SI](#quick-si) · [Trace RLC](#trace-rlc--impedance) |
| Improve layout | [Fanout](#fanout-generator) · [Guard vias](#via-stitching) · [Trace Refiner](#trace-refiner) · [Silkscreen](#silkscreen-label-placer) |
| Coordinate tools | [Assistant](#wayricad-assistant) · [All plugin guides](#all-24-plugins) |

### [WayriCAD Assistant](suite_assistant_plugin/README.md)

**Interpret a request and review its inputs**

<a href="suite_assistant_plugin/help-plan.png"><img src="suite_assistant_plugin/help-plan.png" width="960" alt="Native Assistant interpretation and parameter review"></a>

The testing package uses local fuzzy matching and registered CLI actions.
This plan view is shown before execution; it does not claim a simulation result.

**Select exact nets on the saved board**

<a href="suite_assistant_plugin/help-board-selection.png"><img src="suite_assistant_plugin/help-board-selection.png" width="960" alt="Assistant highlighting the selected public Marble net while muting other copper"></a>

Public Marble, read-only. Exact selected copper is highlighted; zone borders
remain outlines. [Workflow and native-capture scope](suite_assistant_plugin/README.md).

### [Quick PI](quick_pi_plugin/README.md)


**Current mixed loads and grouped pins · 3.6.38**

<a href="quick_pi_plugin/help-mixed-loads-3.6.38.png"><img src="quick_pi_plugin/help-mixed-loads-3.6.38.png" width="960" height="541" alt="Quick PI native constant-power and current loads with same-net source and sink pin groups"></a>

Disposable strip, 3.3 V source, 1.65 W grouped IC load and a separate 0.25 A
sink. Actual extracted-copper solve: 0.750252 A total and 1.3862 mW loss.
No mesh-convergence claim. [Inputs and limitations](docs/audits/QUICK_TOOL_VISUALS_3.6.38.md#quick-pi-current-examples).

**PDN and transient setup · 3.6.38**

<a href="quick_pi_plugin/help-transient-results-3.6.38.png"><img src="quick_pi_plugin/help-transient-results-3.6.38.png" width="960" height="606" alt="Quick PI explicit RLC load-step voltage and source-current plots"></a>

Explicit lumped source/path R/L and local C/ESR; 0.1→1 A current step.
This is a network demonstration, with declared inductance and capacitance.
[Setup window](quick_pi_plugin/help-transient-setup-3.6.38.png) ·
[PDN capacitor-bank setup](quick_pi_plugin/help-pdn-setup-3.6.38.png) ·
[Impedance results](quick_pi_plugin/help-pdn-results-3.6.38.png).

**AC copper and return losses · 3.6.38**

<a href="quick_pi_plugin/help-ac-results-3.6.38.png"><img src="quick_pi_plugin/help-ac-results-3.6.38.png" width="960" height="606" alt="Quick PI actual explicit cross-section AC field, impedance and Joule-loss results"></a>

Balanced two-strip cross-section, 5 A DC plus 1 A RMS at 100 kHz; fixed 20 °C
copper. The explicit field solve gives 0.128126 W copper loss. Saved-board return
geometry is not extracted automatically. [Setup](quick_pi_plugin/help-ac-setup-3.6.38.png).


**Ground and return setup:** choose **Rails / ground returns…** for DC ground
drop, or **Return path** for a geometric plane/stitching review. The common
controls stay visible and optional settings stay collapsed.

<a href="quick_pi_plugin/help-return-ground.png"><img src="quick_pi_plugin/help-return-ground.png" width="960" alt="Guided Quick PI return setup with all load mappings together"></a>

Native synthetic staged inputs; this setup image is not a solved power result.

**Earlier Marble geometry preview · 3.6.28**

<a href="quick_pi_plugin/help-marble-geometry-3.6.28.png"><img src="quick_pi_plugin/help-marble-geometry-3.6.28.png" width="960" alt="Quick PI current native +12V geometry preview on public Marble"></a>

Read-only extracted copper and board context. The editable terminal/operating
defaults are not a reviewed power-path study, and no voltage field has been solved.

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
| [AC / SMPS copper methods](quick_pi_plugin/AC_ANALYSIS.md) | Harmonic skin/proximity and Joule-loss model, explicit returns and HV/LV applicability. Included in 3.6.34. |


**Report preview**

![Quick PI report status and evidence](quick_pi_plugin/help-report-review.png)

Rendered synthetic example with explicit model/coverage status; not a passed board qualification.

### [QuickTherm](quick_therm_plugin/README.md)

**Guided heating study · development**

<a href="quick_therm_plugin/examples/quicktherm-heating-study.png"><img src="quick_therm_plugin/examples/quicktherm-heating-study.png" width="834" alt="QuickTherm source watts, cooling and transient timing review"></a>

Review power, boundary assumptions and frame costs before applying or running.
[Inputs and capture scope](quick_therm_plugin/README.md).


**Current component inputs · 3.6.38**

<a href="quick_therm_plugin/examples/quicktherm-input-3.6.38.png"><img src="quick_therm_plugin/examples/quicktherm-input-3.6.38.png" width="960" alt="QuickTherm current component table for declared dissipation, thermal resistances and temperature limits"></a>

Review the included parts, declared loads and limits before running the model.
[Inputs and capture scope](quick_therm_plugin/README.md#current-native-previews).

**Current paired top/bottom inspection · 3.6.38**

<a href="quick_therm_plugin/examples/quicktherm-paired-3.6.38.png"><img src="quick_therm_plugin/examples/quicktherm-paired-3.6.38.png" width="960" alt="QuickTherm current paired board field and component temperature table"></a>

Generated saved-board example, 1.05 W total and explicit forced-air assumptions.
Both faces display one approximate midplane field; the back is mirrored. No
bottom-side footprints are present in this example.

**Current 3D inspection**

<a href="quick_therm_plugin/examples/quicktherm-3d-3.6.38.png"><img src="quick_therm_plugin/examples/quicktherm-3d-3.6.38.png" width="960" alt="QuickTherm current native 3D board temperature overview"></a>

STEP loading is off; component markers are illustrative. [Inputs and capture scope](quick_therm_plugin/README.md#current-native-previews).


<details>
<summary>Earlier large QuickTherm captures · 3.6.28</summary>

<a href="quick_therm_plugin/examples/quicktherm-input-3.6.28.png"><img src="quick_therm_plugin/examples/quicktherm-input-3.6.28.png" width="960" height="533" alt="Earlier QuickTherm input workspace"></a>

<a href="quick_therm_plugin/examples/quicktherm-paired-3.6.28.png"><img src="quick_therm_plugin/examples/quicktherm-paired-3.6.28.png" width="960" height="533" alt="Earlier QuickTherm paired workspace"></a>

<a href="quick_therm_plugin/examples/quicktherm-3d-3.6.28.png"><img src="quick_therm_plugin/examples/quicktherm-3d-3.6.28.png" width="960" height="533" alt="Earlier QuickTherm 3d workspace"></a>

</details>

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


**Report preview**

![QuickTherm report coverage summary](quick_therm_plugin/help-report-review.png)

Rendered synthetic example with explicit model/coverage status; not a passed board qualification.

### [Quick SI](signal_integrity_advisor_plugin/ReadMe.md)

**Guided path and response · development**

<a href="signal_integrity_advisor_plugin/help-guided-setup.png"><img src="signal_integrity_advisor_plugin/help-guided-setup.png" width="794" alt="Quick SI guided source and receiver, explicit line assumptions and optional time response"></a>

Choose the physical path and review explicit assumptions in one form. This is
setup on the public Marble board, not a new solved or measured channel.
[Inputs and capture scope](signal_integrity_advisor_plugin/ReadMe.md).


**Current Marble route and return selection · 3.6.38**

<a href="signal_integrity_advisor_plugin/help-quick-si-3.6.38.png"><img src="signal_integrity_advisor_plugin/help-quick-si-3.6.38.png" width="960" height="541" alt="Quick SI current native Marble route, declared line inputs and return chooser"></a>

U6.8→U54.16, 253.670 mm and three vias. The 1.513645 ns delay uses declared
50 Ω/effective permittivity 3.2, not extracted channel impedance. Native neighbour
inspection also shows local geometry and unknown coupling explicitly.
[Neighbour view](signal_integrity_advisor_plugin/help-neighbours-3.6.38.png) ·
[Inputs and capture scope](docs/audits/QUICK_TOOL_VISUALS_3.6.38.md).

Earlier route and protocol captures follow.


**Return path:** select the actual return below Source/Receiver, or explicitly
confirm the suggested domain. Extra nets, pins and reference overrides are in
**More return options**.

<a href="signal_integrity_advisor_plugin/help-return-setup.png"><img src="signal_integrity_advisor_plugin/help-return-setup.png" width="960" alt="Quick SI simplified return selector and route preview"></a>

Native synthetic route with explicit line assumptions; missing filled return
coverage remains unknown.

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


**Report preview**

![Quick SI report summary](signal_integrity_advisor_plugin/help-report-review.png)

Rendered synthetic example with explicit model/coverage status; not a passed board qualification.

### [Trace RLC / Impedance](trace_impedance_plugin/ReadMe.md)

**Current Marble electrical coverage · 3.6.38**

<a href="trace_impedance_plugin/help-results-3.6.38.png"><img src="trace_impedance_plugin/help-results-3.6.38.png" width="960" height="541" alt="Trace RLC current Marble results with partial coverage reported"></a>

253.670 mm route, three vias, DC resistance 0.978676 Ω. Partial reference coverage
and unknown antipad capacitance remain visible; these are modelled section totals.
[Route window](trace_impedance_plugin/help-path-3.6.38.png) ·
[Capture scope](docs/audits/QUICK_TOOL_VISUALS_3.6.38.md).

Earlier route and AC examples follow.


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

**Read-only rule overview**

<a href="protocol_constraint_composer_plugin/help-readonly-overview.png"><img src="protocol_constraint_composer_plugin/help-readonly-overview.png" width="960" alt="Constraint Studio native fallback with a read-only rule overview and KiCad editor handoff"></a>

Current source leaves individual rule editing to KiCad's Design Rule Editor and
netclass editing to Board Setup. Studio keeps protocol presets, matrices,
reusable sets and reviewed project export. This native fallback capture uses the
public demonstration fixture. [Changes and validation](docs/audits/CONSTRAINT_NATIVE_OVERLAP_2026-10-23.md).

**Earlier worksheet preview**

<a href="protocol_constraint_composer_plugin/help-workflow.png"><img src="protocol_constraint_composer_plugin/help-workflow.png" width="960" alt="Constraint Studio with optional panels closed"></a>

Historical editable UI rendered from a demonstration snapshot. Scope colours are
condition matches, not native DRC results.

### [Mechanical Check](mechanical_check_plugin/README.md)

**3D measurements and height checks**

<a href="mechanical_check_plugin/help-workflow.png"><img src="mechanical_check_plugin/help-workflow.png" width="960" alt="Mechanical Check native STEP board workspace with an edge-to-edge ruler, global height violation markers and a compact findings sidebar"></a>

The fixture deliberately includes height violations and incomplete coverage. [Capture and validation](docs/audits/MECHANICAL_INSPECTION.md).

Mechanical Check has a hideable findings sidebar, clearer filters and detail cards, direct focus/isolation controls, and separate Measure/Display tabs. See the [review workflow](mechanical_check_plugin/README.md#review-findings-without-losing-the-board).

![Mechanical Check revised findings workspace](mechanical_check_plugin/help-review.png)

### [Trace Refiner](trace_refiner_plugin/README.md)

**Validated original/proposed comparison · 3.6.28**

<a href="trace_refiner_plugin/help-validated-comparison.png"><img src="trace_refiner_plugin/help-validated-comparison.png" width="960" alt="Trace Refiner validated side-by-side original and proposed routing"></a>

Disposable five-segment fixture: one proposed replacement, zero new native DRC
findings. Existing baseline findings remain visible; validation is not a blanket
DRC pass.

**After explicit Apply**

<a href="trace_refiner_plugin/help-applied-refinement.png"><img src="trace_refiner_plugin/help-applied-refinement.png" width="960" alt="Trace Refiner after an actual Apply with Undo available"></a>

The first source UUID was retained; Undo restored the original track snapshot.
[Fixture, validation and capture details](docs/audits/ROUTING_README_SCREENSHOTS_2026-10-23.md).

Clean small routing jogs or center existing pad/via track contacts with selected-track, selected-net, net-filter, net-class and layer scopes. Centering only adjusts an endpoint already touching one unambiguous same-net terminal; actual gaps remain unchanged. Preview keeps routing untouched; native connectivity and before/after DRC must pass before Apply. Differential pairs and protected routing remain unchanged. Available as its own PCM package, with offline Help and a CLI for preview, validation and export to a new project.

![Native trace refinement preview](trace_refiner_plugin/help-workflow.png)

Version 0.3.1 includes separate pad/via endpoint centering, metrics, focused review, proposal exclusion and resizable settings and review panels.

![Trace Refiner proposal review](trace_refiner_plugin/help-review.png)

![Trace Refiner adjustable panels](trace_refiner_plugin/help-layout.png)

![Trace Refiner pad and via endpoint centering](trace_refiner_plugin/help-centering.png)

### [Component Arranger](component_arranger_plugin/README.md)

Choose selected parts, PCB groups, schematic sheets or wire clusters; confirm the anchor and highlighted area. Review courtyard-aware placement, capacitor ordering, crossings and length before native validation. Independent package with icon, offline help, adjustable panels and CLI.

![Component Arranger native group preview](component_arranger_plugin/help-workflow.png)

![Component Arranger adjustable panels](component_arranger_plugin/help-layout.png)

### [Layer Counter](layer_counter_plugin/README.md)

Create physical copper-layer labels as a native movable group with a zone-only
keepout. Choose from 24 styles, including mirrored and overlapping core
pairs, then Preview and Add. Available in release 3.6.20 as an independently installable package. [Setup and CLI](layer_counter_plugin/README.md).

![Layer Counter native-rendered four-layer preview](layer_counter_plugin/help-preview.png)

The shared native preview renderer shows L3/L4 mirrored. These are off-screen
preview renders, not window screenshots.

![Twelve added Layer Counter styles](layer_counter_plugin/help-styles.png)

### [Silkscreen Label Placer](silkscreen_label_plugin/README.md)

Arrange visible reference labels with a simple Preview → Apply flow. Preserve acceptable labels, then try footprint-axis placement, bounded sizes and staggered edge slots. Leaders are off by default; optional short straight guides are audited and removable. Hidden/locked text stays untouched and unresolved placements remain listed.

![Current native synthetic edge-aligned label preview](silkscreen_label_plugin/help-edge-alignment.png)

Current native canvas render on a public synthetic 100-part fixture; no unresolved labels or guides. The retained window and dense-board captures below show earlier controls.

![Native silkscreen placement window](silkscreen_label_plugin/help-workflow.png)

![Dense 100-part label placement preview](silkscreen_label_plugin/help-dense.png)

**Sizing, reading direction and formatting**

<a href="silkscreen_label_plugin/help-typography.png"><img src="silkscreen_label_plugin/help-typography.png" width="480" alt="Silkscreen automatic text sizing and reading direction options"></a>
<a href="silkscreen_label_plugin/help-formatting.png"><img src="silkscreen_label_plugin/help-formatting.png" width="480" alt="Silkscreen formatting rules for test points and connectors"></a>

These options stay separate from the simple main workflow. Native fabrication minimums always apply; formatting patterns are editable to match your board.

### [Fanout Generator](fanout_generator_plugin/ReadMe.md)

[Marble BGA, connector and partial-routing trials](docs/audits/FANOUT_REAL_BOARD_TRIALS_2026-10-23.md)
record current failures as well as the two reproduced bugs fixed in source.
Complete dense-board fanout remains unvalidated; the fixture previews below
show narrower workflows.

**Connector before and proposed after · 3.6.28**

<a href="fanout_generator_plugin/help-connector-before.png"><img src="fanout_generator_plugin/help-connector-before.png" width="960" alt="Fanout connector Before view with existing pads and no proposed copper displayed"></a>

<a href="fanout_generator_plugin/help-connector-proposed.png"><img src="fanout_generator_plugin/help-connector-proposed.png" width="960" alt="Fanout connector After preview with six accepted exits and the selected-component thumbnail"></a>

Actual native window on a six-pin generated connector. All six proposals were
accepted; Apply created 12 tracks and Undo removed them. This fixture is separate
from the full-board Marble trials and does not establish dense-BGA completion.

**Guided review on Marble · 3.6.28**

<a href="fanout_generator_plugin/help-guided-preview.png"><img src="fanout_generator_plugin/help-guided-preview.png" width="960" alt="Fanout guided workspace with actual Marble component thumbnail, accepted and rejected counts, and accessible action buttons"></a>

Actual accepted candidates appear in teal; existing geometry provides context.
This read-only preview is not a completed or DRC-qualified route.

**Live style preview**

Select components or pins, choose a style and inspect its actual fanouts in the
small component preview and main canvas. Apply remains separate.

<a href="fanout_generator_plugin/help-live-preview.png"><img src="fanout_generator_plugin/help-live-preview.png" width="960" alt="Live selected-component fanout style preview"></a>


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


### [Project Fusion](project_fusion_plugin/README.md)

**Guided import**

<a href="project_fusion_plugin/help-guided-import.png"><img src="project_fusion_plugin/help-guided-import.png" width="960" alt="Project Fusion guided source and import review"></a>

Inspect the detected source scope and proposed changes before applying an import
or linked update. Existing layout and schematic update policies remain explicit.

**Variant destination choices**

<a href="project_fusion_plugin/help-variant-destination.png"><img src="project_fusion_plugin/help-variant-destination.png" width="960" alt="Project Fusion source variant and destination policy choices"></a>

Review whether the source variant is merged into a working variant or retained separately.

### [Variant Manager](variant_manager_plugin/README.md)

**Assembly comparison**

<a href="variant_manager_plugin/help-workspace.png"><img src="variant_manager_plugin/help-workspace.png" width="960" alt="Variant Manager native assembly comparison"></a>

Compare saved and staged assembly states, with bulk operations and reviewed recovery.

### [Via Stitching](via_stitching_plugin/ReadMe.md)

**Guard a selected signal · 3.6.28**

<a href="via_stitching_plugin/help-guard-preview.png"><img src="via_stitching_plugin/help-guard-preview.png" width="960" alt="Native guard-stitching preview with separate signal and guard nets, side and offset controls, and 22 proposed through-vias"></a>

Generated two-plane fixture with 22 proposed GND through-vias. Native DRC after
refill added no findings. A one-plane negative fixture produced dangling-via
warnings; geometric clearance alone does not establish a useful return path.
[Workflow and limitations](via_stitching_plugin/ReadMe.md#guard-a-signal-route).

### [Embed3D](embed_3d_plugin/README.md)

<a href="embed_3d_plugin/help-project-library.png"><img src="embed_3d_plugin/help-project-library.png" width="960" alt="Embed3D full-project localization and library preview"></a>

Review the proposed local libraries and models before exporting a portable project.

### [Pin Extractor](extract_pins_plugin/ReadMe.md)

<a href="extract_pins_plugin/help-workflow.png"><img src="extract_pins_plugin/help-workflow.png" width="960" alt="Pin Extractor selection, connectivity and export preview"></a>

Choose exact scope and fields, inspect the pin map, then export tables or diagrams.

### [Harness and Cable Workbench](harness_workbench_plugin/ReadMe.md)

<a href="harness_workbench_plugin/help-workflow.png"><img src="harness_workbench_plugin/help-workflow.png" width="960" alt="Harness and Cable Workbench native connector mapping workspace"></a>

Review explicit connector and wire mappings; a PCB net alone cannot infer an external cable.

### [Bulk Label Editor](bulk_label_editor_plugin/ReadMe.md)

**Current net inventory and text preview · 3.6.38**

<a href="bulk_label_editor_plugin/help-nets-3.6.38.png"><img src="bulk_label_editor_plugin/help-nets-3.6.38.png" width="960" height="550" alt="Bulk Label Editor current public Marble net browser with connection counts"></a>

Marble: 1,374 named nets and 35,765 text fields. The MDC net has two pads,
31 tracks and three vias. Electrical net names are read-only.
[Reference replacement preview](bulk_label_editor_plugin/help-preview-3.6.38.png).

**Earlier text-review window**


<a href="bulk_label_editor_plugin/help-workflow.png"><img src="bulk_label_editor_plugin/help-workflow.png" width="960" alt="Bulk Label Editor native field and text review"></a>

Select the text/field scope, review proposed changes and apply them explicitly.

### [Copper Balancer](copper_balancer_plugin/README.md)

<a href="copper_balancer_plugin/help-diagnostics.png"><img src="copper_balancer_plugin/help-diagnostics.png" width="960" alt="Copper Balancer synthetic board density diagnostics"></a>

Synthetic density example. Inspect exclusions and generated copper before export and native DRC.

### [PCB / Foil Heater Designer](heater_designer_plugin/ReadMe.md)

<a href="heater_designer_plugin/help-workflow-3.6.38.png"><img src="heater_designer_plugin/help-workflow-3.6.38.png" width="960" height="564" alt="Heater Designer current native serpentine geometry preview"></a>

Current 3.6.38 native preview: 80 × 50 mm serpentine, 35 µm copper, 12 V;
3.940 Ω and 36.55 W illustrative electrical loading. No thermal solve or apply.
<details>
<summary>Earlier large native Heater Designer preview</summary>

<a href="heater_designer_plugin/help-workflow.png"><img src="heater_designer_plugin/help-workflow.png" width="960" alt="Earlier Heater Designer native geometry preview"></a>

</details>

Review geometry, material assumptions and the selected thermal/electrical model.

### [Manufacturing Readiness](manufacturing_readiness_plugin/ReadMe.md)

<a href="manufacturing_readiness_plugin/help-workflow.png"><img src="manufacturing_readiness_plugin/help-workflow.png" width="960" alt="Manufacturing Readiness native findings and review workspace"></a>

Review fabrication findings against your manufacturer's actual requirements.

## Help and upgrades

| Topic | Guide |
|---|---|
| Instructions for a specific plugin | [All 24 offline guides](docs/HELP_INDEX.md) |
| Small panels, clipped tables or hidden options | [Resize, scroll and read complete values](docs/UI_ACCESSIBILITY.md) |
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

Use `wayricad tools list` to discover all 24 command interfaces, `wayricad tools doctor` to check an interpreter, and `wayricad tools run TOOL -- --help` for detailed options. The [all-tools CLI catalogue](docs/TOOL_CLI_CATALOGUE.md) includes multi-net PI/SI studies, thermal reports and repeatable jobsets.

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
compatibility. Validation records are in [the release audit](docs/audits/RELEASE_3.6.33.md).

## Acknowledgements and AI disclosure

WayriCAD uses AI assistance for development, research and documentation;
maintainers remain responsible for validation and releases.

| Project information | Reference |
|---|---|
| Maintainer | [Wayri (Yawar)](https://github.com/wayri) |
| WayriCAD license | [GPL-3.0](LICENSE) |
| Fusion and Variant Manager | MIT licensed; see each package's license |
| Credits and AI assistance | [Acknowledgements](ACKNOWLEDGEMENTS.md) |
