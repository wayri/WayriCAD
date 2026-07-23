# KiWay Extract Pins Plugin

A comprehensive KiCAD plugin for extracting component/pin data and analyzing signal flow. Features both GUI and CLI interfaces.

![Version](https://img.shields.io/badge/Version-2.14.1-blue)
![KiCAD](https://img.shields.io/badge/KiCAD-9.0+-green)
![License](https://img.shields.io/badge/License-GPL--3.0-orange)

## Features

### Data Extraction
- Extract pin and net information from any component
- Filter by reference pattern (`J*`, `U*`, etc.), value, or connector type
- Export to clean **CSV**, **Markdown**, or **JSON** formats
- Support for custom `connector-type` properties
- Preserve native hierarchical schematic sheet paths from KiCad XML netlists
- Define sheet display aliases with path and component-reference wildcards
- Import pin documents from other projects and build cross-board signal trackers
- Auto-link exact or normalized labels and apply custom wildcard/regex rules
- Export cross-project tracker CSV/Markdown and harness-style SVG diagrams

### Signal Flow Analysis
- Generate consolidated source-to-destination signal flow tables
- Trace connections between connectors, ICs, and passives
- Find all signal paths between any two components
- Identify intermediate components in signal chains
- Show source and destination pin lists, net class, protocol, path, and link count
- Double-click a route to highlight its net in PCB Editor

### Wildcard Label Endpoint Trace
- Match label/net families such as `*TM`, `*_TD`, or `DEMO_CTRL_*`
- Resolve exact or wildcard endpoint sets such as `U1,U2`, `J1,U1`, or `U*`
- Trace across user-approved resistor/filter/jumper references and `NetTie_Path` parts
- Report endpoint pins, pin functions, terminal nets, ordered intermediate components, and complete paths
- Export software and harness endpoint maps to CSV or Markdown

### IC Signal Charts
- Create complete pin-to-destination mapping for ICs
- Optionally include or exclude power/ground nets
- Group and sort power nets separately from signals
- Preview the IC connectivity as an embedded visual flow diagram
- Perfect for documentation and debugging

### Block Diagrams (NEW!)
- Generate SVG block diagrams - fully self-contained, no external dependencies
- Show every component once in a harness-style component/net topology
- Use distinct signal, supply, power, and ground bus colors with pin labels
- Switch between system map, signal topology, and directed power flow
- Zoom with the mouse wheel, drag to pan, fit/restore the image, and click nets to highlight them in KiCad

### Power Net Classification
- Automatic detection of power/ground nets (VCC, VDD, GND, VSS, voltage rails, etc.)
- Sort and group power nets separately from signal nets
- User-defined power, supply, ground, and forced-signal wildcard patterns
- Shared classification rules across extraction, signal flow, IC charts, and diagrams
- Auto-extracted converter/filter power tree with editable rules and issue checks
- Power-tree SVG and CSV export, including inferred direction and confidence

### CLI Support (NEW!)
- Full command-line interface for automation
- Batch processing of multiple boards
- Integration with build systems and CI/CD
- All GUI features available from command line

---

## Installation

### Method 1: Plugin Manager (Recommended)
1. Open KiCAD → `Plugin and Content Manager`
2. Add repository: `https://raw.githubusercontent.com/wayri/KiWay/develop/pcm/repo.json`
3. Search for "KiWay" and install

### Method 2: Manual Installation
1. Enable the KiCAD API: `Preferences → Preferences → Plugins → Enable`
2. Open PCB Editor → `Tools → Plugins → Open Plugin Directory`
3. Copy the `extract_pins_plugin` folder to the plugin directory
4. `Tools → Plugins → Refresh Plugins`

---

## Usage

### GUI Mode
1. Open your PCB in the PCB Editor
2. *(Optional)* Select components on the PCB
3. `Tools → External Plugins → Extract Component Pins with GUI`
4. Use **Extract Pins** to follow PCB selection, filter components, preview rows, and export
5. Use **Signal Flow** and **IC Signal Chart** to review table and visual connectivity
6. Use **Power Tree & Net Rules** to define classification wildcards and build the checked rail tree

Double-click an extracted pin, signal-flow route, or IC-chart row to highlight its
net in PCB Editor. **Select Copper** selects matching tracks, vias, and zones for
native KiCad operations. The **Help** button opens the bundled guide inside a
native KiCad window and provides an external-browser fallback.

### CLI Mode (Installed Plugin)

### Hierarchical Sheet Definitions

The **Sheet Definitions** tab shows sheets detected from each XML netlist's
`sheetpath` metadata. Optional rules use this format:

```text
Display Name | /native/sheet/path/* | reference wildcard
```

Rules are evaluated from top to bottom and both filters must match. Examples:

```text
Channel 1 Power | /Power/Channel1/* | *
Control MCU | * | U1
Connector Sheets | /Interfaces/* | J*
```

The resolved sheet name and native path are included in TM/TC, test-point,
connector, peripheral, and component exports.

### Cross-Project Pin Linking

Use the **Cross-Link** tab to import KiWay CSV or Markdown pin documents from
multiple projects. The current PCB can be added directly. Exact and normalized
label matching are available by default; power rails are opt-in.

Custom rules use:

```text
Rule Name | wildcard | DEMO_CTRL_* | DEMO_SENSOR_*
Harness || regex || ^SRC_(?P<signal>.+)$ || ^DST_(?P<signal>.+)$
```

Wildcard `*` and `?` captures, or regex capture groups, must resolve to the
same text. Use the `||` delimiter when a regex contains `|` alternation. The
tracker records project, board, sheet, component, pin, label, match method,
rule, confidence, and ambiguity status. Export it to CSV/Markdown or generate
a multi-project harness SVG.

```bash
# Basic extraction - all J* connectors to CSV
python -m extract_pins_plugin extract --refs "J*" --format csv board.kicad_pcb
```

### CLI Mode (Standalone / Without Installation)
You can run the plugin directly from the downloaded folder without installing it into KiCad, as long as you use KiCad's bundled Python.

**Windows:**
```cmd
"C:\Program Files\KiCad\9.0\bin\python.exe" -m extract_pins_plugin extract --refs "J*" "C:\path\to\your\board.kicad_pcb"
```

**Linux/Mac:**
If you have the `pcbnew` python module available in your system python:
```bash
export PYTHONPATH=$PYTHONPATH:/usr/share/kicad/scripting/plugins
python3 -m extract_pins_plugin extract --refs "J*" board.kicad_pcb
```

---

## CLI Commands Reference

### `extract` - Extract component/pin data
```
--refs          Reference patterns (wildcards: *, ?)
--connector-types  Filter by connector-type property
--value-filter  Filter by component value
--net-filter    Filter by net name (comma-separated patterns)
--ignore-unconnected  Skip 'unconnected' pins
--ignore-free   Skip pins with no net
--ignore-power  Skip power/ground nets
--sort-by-net-type  Sort signals before power
--format        csv, md, json (default: csv)
```

### `signal-flow` - Source/destination table
```
--source        Source components (wildcards supported)
--dest          Destination components (wildcards supported)
--intermediates Include intermediate components
--format        csv, md, json, svg
```

### `ic-chart` - IC signal chart
```
--ic            IC reference (wildcards for batch)
--include-power Include power nets
--power-nets    Custom power net patterns
--format        csv, md, json, svg
```

### `diagram` - SVG block diagrams
```
--refs          Component references (wildcards supported)
```

### `unique-nets` - Extract unique net names
```
--sort-by-type  Group signals first, then power, then ground
```

### `find-path` - Find signal paths
```
--start         Starting component
--end           Ending component
--max-hops      Maximum hops (default: 10)
```

### `list` - List board components
```
--refs          Filter by reference pattern
```

---

## Wildcard Patterns

All reference and filter arguments support wildcards:

| Pattern | Matches |
|---------|---------|
| `J*` | J1, J2, J10, JCONN1 |
| `U?` | U1, U2, but not U10 |
| `J*,U*` | All J and U components |
| `SPI_*` | SPI_MOSI, SPI_CLK, etc. |
| `*GND*` | Any net containing GND |

---

## Output Formats

### CSV
Clean, one-row-per-pin format ideal for spreadsheet analysis.

### Markdown
Human-readable tables with optional net highlighting.

### JSON
Structured data for programmatic processing.

### SVG
Self-contained vector diagrams with:
- Color-coded net types (signal/power/ground)
- Component blocks with pin details
- Connection paths with labels
- Legend and summary

---

## License

GPL-3.0 - See [LICENSE](LICENSE) for details.

## Author

**Wayri (Yawar)**
- GitHub: [@wayri](https://github.com/wayri)
