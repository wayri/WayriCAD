# KiWay Extract Pins Plugin

A comprehensive KiCAD plugin for extracting component/pin data and analyzing signal flow. Features both GUI and CLI interfaces.

![Version](https://img.shields.io/badge/Version-2.7.0-blue)
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

### Signal Flow Analysis
- Generate source-to-destination signal flow tables
- Trace connections between connectors, ICs, and passives
- Find all signal paths between any two components
- Identify intermediate components in signal chains

### IC Signal Charts
- Create complete pin-to-destination mapping for ICs
- Optionally include or exclude power/ground nets
- Group and sort power nets separately from signals
- Perfect for documentation and debugging

### Block Diagrams (NEW!)
- Generate SVG block diagrams - fully self-contained, no external dependencies
- Visualize IC signal connections with color-coded net types
- Create signal flow diagrams between component groups

### Power Net Classification
- Automatic detection of power/ground nets (VCC, VDD, GND, VSS, etc.)
- Sort and group power nets separately from signal nets
- Customizable power net patterns

### CLI Support (NEW!)
- Full command-line interface for automation
- Batch processing of multiple boards
- Integration with build systems and CI/CD
- All GUI features available from command line

---

## Installation

### Method 1: Plugin Manager (Recommended)
1. Open KiCAD → `Plugin and Content Manager`
2. Add repository: `https://raw.githubusercontent.com/wayri/KiWay/main/pcm/repo.json`
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
4. Use the dialog to filter, configure, and export

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
