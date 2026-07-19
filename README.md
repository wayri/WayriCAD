# KiWay Plugins for KiCad

KiWay is a parent repository for KiCad ActionPlugins that can be added to KiCad's Plugin and Content Manager (PCM). Each plugin lives in its own package directory and is indexed through `pcm/repo.json` and `pcm/pkgs.json`.

## List of Plugins

### 1. KiWay Extract Pins (v2.2.0)

A comprehensive interface documentation and test engineering tool.

- **Graph Tracing**: Build a `networkx` graph from pcbnew board data and optional KiCad XML netlists
- **Smart Paths**: Traverse passive in-path components and custom `NetTie_Path` pass-throughs
- **Test Points**: Resolve TP nets back to source IC pins/functions
- **TM/TC Tables**: Parse labels such as `DEMO_CTRL_DEMO_SENSOR_SIGNAL_SPI1_CLK_1_TD`, including `TM`, `TC`, `TA`, `TD`, `CA`, and `CD`
- **Hierarchical Sheets**: Detect native sub-sheet paths and apply user-defined path/reference aliases to exported records
- **Cross-Project Links**: Import pin CSV/Markdown documents, auto-link board endpoints, and export tracker and harness diagrams
- **Interfaces**: Group buses, differential pairs, connectors, peripherals, and board-to-board signal maps
- **Layout Assist**: Create native KiCad PCB groups for logical interfaces
- **Docs**: Export Markdown, HTML, CSV, JSON, SVG diagrams, and automation-friendly CLI output

### 2. KiWay Bulk Label Editor (v0.2.0)

A preview-and-apply editor for repeated channel labels and component text.

- Wildcard replacement, e.g. `CH*_MAIN` -> `CH*_REDUNDANT`
- Regex replacement for advanced renaming
- Scoped edits for footprint references, values, custom fields, and PCB text

### 3. KiWay Fanout Generator (v0.2.0)

Creates conservative radial fanout tracks from a selected footprint or all SMD footprints, preserving pad layer and net assignment. Track width and fanout length are configurable.

### 4. KiWay Via Stitching (v0.2.0)

Creates a configurable via-stitching grid inside the board outline bounding box. Select a net to stitch, or create unconnected vias, and skip footprint bodies, chosen references, tracks, zones, and board drawings/keepouts.

### 5. KiWay Connector ICD Builder (v0.1.0)

Detects connector-like footprints and exports connector, part, pin, net, and pad-type tables to CSV for ICD and harness reviews.

### 6. KiWay Net Hygiene (v0.1.0)

Scans for unconnected pads, duplicate references, single-pad nets, and suspicious net names, then exports a review CSV.

### 7. KiWay Test Coverage Planner (v0.1.0)

Reports every board net with its TP/TestPoint coverage status, test-point references, and coverage count.

### 8. KiWay Test Point Descriptor Extractor (v0.1.0)

Extracts TP/TestPoint footprint descriptors, connected nets, board-to-board source/destination labels, and TM/TC classification to CSV, Markdown, or HTML.

- Configurable descriptor field, with fallback to `Descriptor`, `Function`, or `Description`
- Parses labels such as `DEMO_CTRL_DEMO_SENSOR_SIGNAL_SPI1_CLK_1_TD`
- Includes TP reference, value, footprint, pad, net, descriptor, signal, board endpoints, and notes
- Exports documentation directly from the open PCB

### 9. KiWay Trace RLC / Impedance Analyzer (v0.1.0)

Measures routed net geometry between selected start/end pads and reports first-order resistance, capacitance, inductance, impedance, layer changes, vias, and same-net copper zones. It supports optional differential-mate comparison and stackup/reference-layer inputs.

The analyzer is intended for design review and estimation. Critical high-speed interfaces still require field-solver, TDR, or laboratory validation.

## Planned Enhancements

- **Fanout improvements**: BGA/QFN escape strategies, differential-pair fanout, length-aware escape patterns, rule-driven layer assignment, and review overlays.
- **Via stitching improvements**: Copper-zone awareness, shielding fences, RF keepout support, return-path stitching, and DRC-friendly presets.
- **Connector ICD improvements**: Multi-board connector maps, pin compatibility checks, mating connector BOM validation, and mismatch reports.
- **Net hygiene improvements**: Naming-convention linting, source/destination inference, power-domain checks, and orphan-signal reports.
- **Test coverage improvements**: Coverage scoring per interface, fixture probe planning, and manufacturing test exports.

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

```bash
python -m pip install -e .
kiway --help
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

# Run synthetic, non-flaky scaling checks.
kiway benchmark --nets 10000 --boards 8 --threshold-ms 10000 --format json

# Run the repository test suite.
kiway test
```

The CLI returns `0` for success, `1` for runtime failures, `2` for usage/config
errors, and `3` for validation failures. JSON output is sorted and indented for
deterministic automation diffs. Config files are JSON objects with optional
`defaults` and per-command sections; CLI flags override config values.

## Documentation

- [Extract Pins Plugin Documentation](extract_pins_plugin/ReadMe.md)
- [Developer Wiki](https://github.com/wayri/KiCAD_Plugins/wiki/KiCad-Pin-Extraction-Plugin:-Developer-Documentation)
