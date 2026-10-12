# WayriCAD

**19 independently installable KiCad plugins** for PCB design, analysis and project review.
Install just the tools you need. Processing runs locally after dependency setup.
**KiCad 10 is the validated target**; see [compatibility](docs/COMPATIBILITY.md) for platform limits.

[Download 3.6.16](https://github.com/wayri/WayriCAD/releases/tag/v3.6.16) · [Release notes](docs/RELEASE_NOTES_3.6.16.md) · [Full user guide](docs/USER_GUIDE.md)

[Install](#install-and-open) · [Getting started](#getting-started) · [All plugins](#all-19-plugins) · [Screenshots](#plugin-previews) · [Help](#help-and-upgrades) · [Development](#automation-and-development)

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
read [installation](docs/INSTALLATION.md), [troubleshooting](docs/TROUBLESHOOTING.md)
and [runtime setup](wayricad_runtime/RUNTIME_SETUP.md).

<a id="choose-a-kicad-workflow"></a>

## Getting started

Save the PCB, refill its zones, and save Board Setup before analysis. Start with
one net or a small component group, then expand the study. Unknown results mean
an input or model is missing; they are not a pass.

### Quick PI — check a power path

1. Open **WayriCAD Quick PI**. In **Setup**, choose the power net, source pad and sink pad.
2. Enter **Source · V** and **Load · A**. Add sink voltage limits or **Additional sinks** if needed.
3. Click **Preview** to inspect the extracted copper, then **Run**.
4. Inspect **Results** for voltage drop, current density and losses. Choose a layer,
   hover for values, and click to pin probes. Use **Export** for HTML and JSON.

For your first run, use the default layered DC model. Review copper thickness,
via plating and mesh refinement before relying on local peaks.
[Quick PI guide](quick_pi_plugin/README.md#workflow).

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
[Step-by-step thermal guide](quick_therm_plugin/QUICK_THERM_USER_GUIDE.md).

### Quick SI — screen a routed signal

1. Open **WayriCAD Quick SI**. Search for a net or use **Select net on board**.
2. Choose source and receiver pads. Review the saved physical stackup and the
   driver/load assumptions, including rise time and resistance.
3. Click **Screen selected path**. Inspect delay, routed sections, impedance coverage
   and reflection estimates; unresolved sections remain visible.
4. Inspect the route and waveform plots, then export HTML/JSON for review.

Automatic timing assumes ideal continuous references where indicated. A mixed
route may have usable section results without a single overall impedance.
[Quick SI guide](signal_integrity_advisor_plugin/ReadMe.md).

### Trace RLC — measure a routed connection

1. Open **Trace RLC / Impedance**, choose the net and two different pads.
2. Select **Path** for connected traces/vias/zones, or **Zone/plane** for a filled
   island with a declared current-corridor width. Use **Auto** reference or select a layer.
3. Run **Analyze**, then inspect the copper preview and per-section R, L, C and impedance.
4. Export the results. Use **Line cross section** for manually entered supported CPW,
   grounded CPW or coupled-stripline geometries.

Automatic board impedance covers supported single-ended microstrip/stripline
sections. Differential-pair mode measures paths/skew; it does not automatically
extract coupled differential impedance. [RLC guide](trace_impedance_plugin/ReadMe.md#workflow).

### BOM Studio workflow — now in Analytics Studio

1. Open **WayriCAD Analytics Studio** from your saved project.
2. In **BOM settings**, choose fields, grouping, sorting and DNP filters.
3. Edit fields in **BOM workspace**, then save the workspace sidecar.
4. Use **Exports & templates** to preview and export a BOM. Use **Review & native sync**
   only when you want reviewed edits written back to the saved KiCad project.

**BOM Studio was renamed Analytics Studio; they are one plugin.** Existing package
IDs and workspace files are retained. Native KiCad exports read saved source;
workspace exports can include staged edits. [BOM workflow guide](bom_studio_plugin/README.md#everyday-workflow).

### Analytics Studio — inspect components and copper

1. Open **Board, copper & components** in Analytics Studio.
2. Review mapped cost, mass and power fields for component analytics.
3. Open **Board & copper** for board area, layer coverage, net/zone copper areas,
   track lengths, via counts and per-component pad-contact areas.
4. Search by net or part, inspect unknowns, and export the tables as CSV, XLSX, JSON or HTML.

Board analytics uses saved geometry and saved zone fills. Pad-contact area means
nominal copper land area, not thermal conductance. Missing values and mixed
currencies stay explicit. [Analytics guide](bom_studio_plugin/README.md).

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

<details>
<summary>Show screenshots</summary>

Demonstration inputs are not predictions for your board. See
[capture provenance](docs/audits/README_GALLERY.md) and each tool's guide.

**[Quick PI](quick_pi_plugin/README.md)**

<a href="quick_pi_plugin/help-workspace.png"><img src="quick_pi_plugin/help-workspace.png" width="800" alt="Native Quick PI board and result workspace"></a>

**[QuickTherm](quick_therm_plugin/README.md)**

<a href="quick_therm_plugin/examples/quicktherm-component-heating.png"><img src="quick_therm_plugin/examples/quicktherm-component-heating.png" width="800" alt="QuickTherm component heating and board results"></a>

**[Quick SI](signal_integrity_advisor_plugin/ReadMe.md)**

<a href="signal_integrity_advisor_plugin/help-workflow.png"><img src="signal_integrity_advisor_plugin/help-workflow.png" width="800" alt="Quick SI routed signal analysis"></a>

**[Trace RLC](trace_impedance_plugin/ReadMe.md)**

<a href="trace_impedance_plugin/help-marble-path.png"><img src="trace_impedance_plugin/help-marble-path.png" width="800" alt="Trace RLC saved-board route analysis"></a>

**[Analytics Studio](bom_studio_plugin/README.md)**

<a href="bom_studio_plugin/help-board-copper.png"><img src="bom_studio_plugin/help-board-copper.png" width="800" alt="Analytics Studio board and copper tables"></a>

**[Constraint Studio](protocol_constraint_composer_plugin/ReadMe.md)**

<a href="protocol_constraint_composer_plugin/help-workflow.png"><img src="protocol_constraint_composer_plugin/help-workflow.png" width="800" alt="Constraint Studio with optional panels closed"></a>

</details>

## Help and upgrades

- [Installation and troubleshooting](docs/TROUBLESHOOTING.md) — missing actions, runtimes and installation paths.
- [Compatibility](docs/COMPATIBILITY.md) — tested hosts and known limits.
- [Analysis models and probes](docs/ANALYSIS_INTERACTIONS.md) — what views and results represent.
- [CLI guide](docs/CLI_USER_GUIDE.md) and [jobsets](wayricad_runtime/JOBSETS.md) — repeatable reports and automation.

<a id="upgrade-safely"></a>

Refresh PCM, install updates and restart PCB Editor. Keep project backups and BOM
workspace files. Remove retired standalone tools to avoid duplicate actions:
PDN Decoupling is in Quick PI; Return-Path Auditor and Test Point Descriptor are
in Quick SI; Embed3D combines Localizer and Portable Assets.

<a id="recommended-system"></a>

Hardware planning details are in [System requirements](docs/SYSTEM_REQUIREMENTS.md).

## Automation and development

Use `wayricad jobs` for repeatable analysis/report sequences and KiCad jobsets.
For source development, read [CONTRIBUTING.md](CONTRIBUTING.md),
[AGENTS.md](AGENTS.md) and [runtime setup](wayricad_runtime/RUNTIME_SETUP.md).

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
maintainers remain responsible for validation and releases. See
[acknowledgements and the full disclosure](ACKNOWLEDGEMENTS.md).

Maintained by [Wayri (Yawar)](https://github.com/wayri).
WayriCAD is [GPL-3.0](LICENSE); Fusion and Variant Manager are MIT licensed.
