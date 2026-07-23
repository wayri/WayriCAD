# KiWay Plugins for KiCad

KiWay is a parent repository for KiCad ActionPlugins that can be added to KiCad's Plugin and Content Manager (PCM). Each plugin lives in its own package directory and is indexed through `pcm/repo.json` and `pcm/pkgs.json`.

## List of Plugins

### 1. KiWay Extract Pins (v2.14.0)

A comprehensive interface documentation and test engineering tool.

- **Graph Tracing**: Build a `networkx` graph from pcbnew board data and optional KiCad XML netlists
- **Smart Paths**: Traverse passive in-path components and custom `NetTie_Path` pass-throughs
- **Test Points**: Resolve TP nets back to source IC pins/functions
- **TM/TC Tables**: Parse labels such as `DEMO_CTRL_DEMO_SENSOR_SIGNAL_SPI1_CLK_1_TD`, including `TM`, `TC`, `TA`, `TD`, `CA`, and `CD`
- **Hierarchical Sheets**: Detect native sub-sheet paths and apply user-defined path/reference aliases to exported records
- **Cross-Project Links**: Import pin CSV/Markdown documents, auto-link board endpoints, and export tracker and harness diagrams
- **Power Architecture**: Define shared power/signal wildcards, inspect consolidated routes, and auto-build checked converter/filter power trees
- **Endpoint Trace**: Resolve wildcard label families such as `*TM` to selected IC/connector pins through user-approved series components
- **Interfaces**: Group buses, differential pairs, connectors, peripherals, and board-to-board signal maps
- **Layout Assist**: Create native KiCad PCB groups for logical interfaces
- **Docs**: Export Markdown, HTML, CSV, JSON, SVG diagrams, and automation-friendly CLI output
- **Live PCB Selection**: Keep the modeless extractor open while selecting footprints and cross-selecting preview rows
- **Visual Preview**: Explore pan/zoom system maps, signal topologies, and directed power-flow diagrams with unique component cards and color-coded net buses
- **Focused Tasks**: Use the simple Pin Extractor for board work and the separate Interboard & Harness entry for system ICD work

### 2. KiWay Bulk Label Editor (v0.6.0)

A preview-and-apply editor for repeated channel labels and component text.

- Wildcard replacement, e.g. `CH*_MAIN` -> `CH*_REDUNDANT`
- Regex replacement for advanced renaming
- Scoped edits for footprint references, values, custom fields, and PCB text

### 3. KiWay Fanout Generator (v0.7.0)

Creates dogbone, BGA/LGA grid, quadrant, four-corner, perimeter, radial, and via-in-pad escapes. Scope generation to selected pads, selected footprints, reference wildcards, or all SMD pads; use the live KiCad-like preview before committing a persistent native PCB group.

### 4. KiWay Via Stitching (v0.7.0)

Creates a configurable stitching grid inside the board outline or the current PCB selection. It can require filled copper on the selected target net and reports candidates rejected by footprint, other-net copper, track/via, keepout, and drawing exclusions before committing a persistent PCB group.

### 5. KiWay Connector ICD Builder (v0.4.1)

Detects connector-like footprints and exports connector, part, pin, net, and pad-type tables to CSV for ICD and harness reviews.

### 6. KiWay Net Hygiene (v0.4.1)

Scans for unconnected pads, duplicate references, single-pad nets, and suspicious net names, then exports a review CSV.

### 7. KiWay Test Coverage Planner (v0.4.1)

Reports every board net with its TP/TestPoint coverage status, test-point references, and coverage count.

### 8. KiWay Test Point Descriptor Extractor (v0.5.0)

Extracts TP/TestPoint footprint descriptors, connected nets, board-to-board source/destination labels, and TM/TC classification to CSV, Markdown, or HTML.

- Configurable descriptor field, with fallback to `Descriptor`, `Function`, or `Description`
- Parses labels such as `DEMO_CTRL_DEMO_SENSOR_SIGNAL_SPI1_CLK_1_TD`
- Traces through common passives and `NetTie_Path` parts to connected IC reference, pin, pin function, terminal net, and complete intermediate path
- Includes TP reference, value, footprint, pad, net, descriptor, signal, board endpoints, and notes
- Exports documentation directly from the open PCB

### 9. KiWay Trace RLC / Impedance Analyzer (v0.5.0)

Measures routed net geometry between selected start/end pads and reports first-order resistance, capacitance, inductance, impedance, layer changes, vias, and same-net copper zones. The result identifies the selected reference layer, dielectric separation, permittivity, and complete parsed stackup used by the estimate.

The analyzer is intended for design review and estimation. Critical high-speed interfaces still require field-solver, TDR, or laboratory validation.

## PCB Editor Workflow

1. Launch **KiWay Pin Extractor** for normal component and net work.
2. Select **PCB selection**, **Wildcard filters**, or **Selection + filters**.
3. Keep **Follow PCB selection** enabled while clicking footprints in PCB Editor.
4. Click **Preview Extraction** and review the native pin table.
5. Double-click a preview row to select its footprint and highlight its net on the PCB.
6. Export the reviewed rows, or open **Block Diagrams** for an interactive system map, signal topology, or directed power-flow preview.

Launch **KiWay Interboard & Harness** separately for netlist directories, sheet aliases, multi-board cross-links, TM/TC, harnesses, and complete ICD reports. Fanout, via stitching, and bulk editing also use modeless staged-preview windows so the PCB remains inspectable while they are open.

## Installation

### Method 1: KiCad Plugin and Content Manager

1. Open the **KiCad Project Manager**.
2. Open **Plugin and Content Manager**.
3. Select the **Repositories** tab.
4. Click **Manage...**.
5. Click the **Add repository** button, then enter this complete URL:

   `https://raw.githubusercontent.com/wayri/KiWay/develop/pcm/repo.json`

6. Confirm the repository and close the repository manager.
7. Select **KiWay Plugin Repository** in the repository dropdown.
8. Select a plugin and click **Install**.
9. Apply the pending changes if KiCad shows an **Apply Pending Changes** button.
10. Restart the KiCad PCB Editor so the ActionPlugins are registered.

If the repository does not appear immediately, close and reopen the Plugin and Content Manager, or remove and re-add the repository URL to clear its cached feed.

The repository feed is also directly viewable here:

`https://raw.githubusercontent.com/wayri/KiWay/develop/pcm/repo.json`

### Method 2: Manual Installation

1. Download a release zip from the repository releases page.
2. Extract the plugin folder into your KiCad third-party plugins directory:
   - Windows KiCad 10 scripting plugins: `%APPDATA%\kicad\10.0\scripting\plugins\`
   - Linux KiCad 10 scripting plugins: `~/.local/share/kicad/10.0/scripting/plugins/`
   - macOS KiCad 10 scripting plugins: `~/Library/Application Support/kicad/10.0/scripting/plugins/`
3. Restart KiCad.

For an existing KiCad 10 Windows installation, the scripting plugin directory is usually:

`%APPDATA%\kicad\10.0\scripting\plugins\`

## Building PCM Packages

Run:

```bash
python build_pcm.py
```

The builder discovers every top-level plugin directory containing `metadata.json`, creates a release zip under `releases/`, and updates `pcm/pkgs.json` plus `pcm/repo.json`.

## KiWay CLI

KiWay also installs a normal Python CLI that can run outside KiCad for netlist,
ICD, validation, cross-project, and automation workflows:

See the [detailed CLI user guide](docs/CLI_USER_GUIDE.md) for complete command
coverage, configuration files, CI examples, and KiCad `.kicad_jobset`
integration.

```bash
python -m pip install -e .
kiway --help

# Check the current Python environment and every KiWay suite package.
kiway dependencies

# Review the exact user-site pip command without changing the environment.
kiway dependencies --install --dry-run
```

KiCad PCB extraction still requires KiCad's `pcbnew` Python module, but XML
netlist, CSV, Markdown, report, validation, cross-link, and benchmark commands
run in standard Python.

Common commands:

```bash
# Inspect one project or a directory of KiCad XML/.net exports.
kiway inspect path/to/project_exports --board-sequence DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO --format json

# Extract telemetry/command rows from hierarchical netlists.
kiway extract project.xml --kind tm-tc --consolidate --board-sequence DEMO_CTRL,DEMO_SENSOR --format csv -o tm_tc.csv

# Extract connector rows and preserve native sheet paths with aliases.
kiway extract project.xml --kind connectors --sheet-alias "ADCS IMU:/Main/ADCS/*:U*" --format md

# Link board exports with exact, normalized, wildcard, or regex rules.
kiway crosslink DEMO_CTRL_pins.csv DEMO_SENSOR_pins.md --project DEMO_CTRL --project DEMO_SENSOR --rules "Board prefix | wildcard | DEMO_CTRL_* | DEMO_SENSOR_*" --format json -o cross_links.json

# Generate a harness-style SVG from imported project documents.
kiway crosslink DEMO_CTRL_pins.csv DEMO_SENSOR_pins.md --rules "Board prefix | wildcard | DEMO_CTRL_* | DEMO_SENSOR_*" --format svg -o harness.svg

# Validate aerospace interface conventions with machine-readable diagnostics.
kiway validate project.xml --board-sequence DEMO_CTRL,DEMO_SENSOR --require-tm-consumer --require-tc-origin --diagnostics json --format json

# Build a full ICD report.
kiway report project.xml --board-sequence DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO --title "DEMO_CTRL Electrical ICD" --format html -o DEMO_CTRL_icd.html

# Run a KiCad jobset using the native kicad-cli backend.
kiway jobset-run project.kicad_pro --file release.kicad_jobset --stop-on-error

# Run synthetic, non-flaky scaling checks.
kiway benchmark --nets 10000 --boards 8 --threshold-ms 10000 --format json

# Run the repository test suite.
kiway test
```

Inside KiCad, open **KiWay Interboard & Harness** and click
**Dependencies...** to check the bundled KiCad Python runtime, dependency
versions, user-site target, and all installed KiWay packages. Install actions
show the exact command for confirmation and never write into KiCad's
`Program Files` directory. Restart PCB Editor after installing dependencies.

ActionPlugin registration is guarded by a running wx application, so standalone
module imports no longer call KiCad's registration API. Use `kiway dependencies`,
`compileall`, or the integrated dependency manager for repeatable health checks.

The CLI returns `0` for success, `1` for runtime failures, `2` for usage/config
errors, and `3` for validation failures. JSON output is sorted and indented for
deterministic automation diffs. Config files are JSON objects with optional
`defaults` and per-command sections; CLI flags override config values.

## Documentation

- [Extract Pins Plugin Documentation](extract_pins_plugin/ReadMe.md)
- [CLI User Guide and Jobset Integration](docs/CLI_USER_GUIDE.md)
- [Fanout Generator Documentation](fanout_generator_plugin/ReadMe.md)
- [Via Stitching Documentation](via_stitching_plugin/ReadMe.md)
- [Test Point Descriptor Documentation](test_point_descriptor_plugin/ReadMe.md)
- [Trace RLC / Impedance Documentation](trace_impedance_plugin/ReadMe.md)
- [Contributing](CONTRIBUTING.md)
- [Developer Wiki](https://github.com/wayri/KiCAD_Plugins/wiki/KiCad-Pin-Extraction-Plugin:-Developer-Documentation)

## Acknowledgements

KiWay is built on the work of the open-source electronic-design and Python
communities. In particular, the project acknowledges:

- [KiCad](https://www.kicad.org/) and its contributors for the EDA suite,
  `pcbnew` Python API, file formats, and Plugin and Content Manager ecosystem.
- [wxPython](https://wxpython.org/) for the native desktop user interfaces.
- [NetworkX](https://networkx.org/) for connectivity graphs and path traversal.
- [Matplotlib](https://matplotlib.org/) and
  [Python-Markdown](https://python-markdown.github.io/) for optional diagrams
  and documentation previews.
- KiWay users and contributors who report PCB workflow issues, test releases,
  propose features, and contribute code or documentation.

KiCad and the named projects are independent projects. Their inclusion here
does not imply sponsorship or endorsement of KiWay.

## License

KiWay is free software licensed under the
[GNU General Public License, version 3 only](LICENSE) (`GPL-3.0-only`). You may
use, study, modify, and redistribute it under the terms of that license. Any
redistributed modified or unmodified KiWay source must retain the applicable
license and copyright notices and provide the corresponding source as required
by the GPL.

Third-party projects and dependencies remain subject to their own licenses.
Generated Markdown, CSV, HTML, JSON, and diagram exports describe the user's
design data and are not automatically relicensed as KiWay source code merely
because KiWay generated them.
