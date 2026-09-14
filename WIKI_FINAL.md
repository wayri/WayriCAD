# WayriCAD Extract Pins Plugin

**WayriCAD Extract Pins** is a powerful KiCAD plugin designed to automate documentation and signal analysis. It allows you to extract pin data, trace signal flows, and generate diagrams directly from your PCB layout.

## Features at a Glance

| Feature | Description |
|---------|-------------|
| **Data Extraction** | Export pinouts to CSV, Markdown, or JSON. Filter by reference, value, or connector type. |
| **Signal Flow** | Trace signals from Source to Destination (e.g., Connector → IC). |
| **IC Charts** | Generate complete pin maps for ICs, showing where every pin connects. |
| **Visual Diagrams** | **NEW!** Generate self-contained SVG block diagrams and flowcharts. |
| **Automation** | **NEW!** Full CLI support for scripting and CI/CD integration. |

---

# Installation

### Method 1: Plugin Manager (Recommended)
1. Open **KiCAD 9.0+**.
2. Go to **Plugin and Content Manager**.
3. Click **Manage Repositories** -> **(+) Add**.
4. URL: `https://raw.githubusercontent.com/wayri/WayriCAD/main/pcm/repo.json`
5. Click **Save**, then select "WayriCAD Plugins" from the repository dropdown.
6. Install **WayriCAD Extract Pins**.

### Method 2: Manual Install
Download the latest release zip and extract the `extract_pins_plugin` folder to:
- **Windows**: `Documents\KiCad\9.0\scripting\plugins\`
- **Linux**: `~/.local/share/kicad/9.0/scripting/plugins/`

---

# GUI Usage Guide

The GUI is designed for interactive exploration.

1. **Open PCB Editor**: Launch your board layout.
2. **Launch Plugin**: Click the toolbar icon or go to `Tools -> External Plugins -> Extract Component Pins`.
3. **Select Components**: You can select components on the PCB *before* or *during* the plugin session.
   - **Auto-Refresh**: Enable this checkbox to have the list update automatically as you click components on the board.

![User Flow](https://raw.githubusercontent.com/wayri/WayriCAD/main/extract_pins_plugin/UserFlow.svg)

### Tabs Overview
- **Extract Pins**: The main table view. Configure filters and export pin lists.
- **Signal Flow**: Define a "Source" (e.g., `J1`) and "Destination" (e.g., `U1`). The plugin will find all nets connecting them.
- **IC Chart**: Pick an IC (`Uxx`) to see a report of all its connections.
- **Diagrams**: Generate visual block diagrams.

---

# CLI Reference (Command Line)

You can use WayriCAD without opening the KiCAD GUI. This is perfect for generating documentation automatically.

**Note**: You must run these commands using KiCAD's bundled Python environment.

### 1. Basic Extraction (`extract`)
Export pin data for components.

```bash
# Export all connectors starting with J to CSV
wayricad-python -m extract_pins_plugin extract --refs "J*" --format csv board.kicad_pcb
```

**Options:**
- `--refs "J*,P*"`: Select components by reference patterns.
- `--net-filter "SPI_*"`: Only show pins connected to nets matching the pattern.
- `--ignore-power`: Exclude GND/VCC pins.

### 2. Signal Flow Analysis (`signal-flow`)
Trace signals between two sets of components.

```bash
# Trace signals from Connector J1 to Microcontroller U1
wayricad-python -m extract_pins_plugin signal-flow --source "J1" --dest "U1" --format md board.kicad_pcb
```

**Output Example (Markdown):**
| Source | Pin | Net | Dest | Pin |
|--------|-----|-----|------|-----|
| J1 | 1 | SPI_MOSI | U1 | 14 |
| J1 | 2 | SPI_MISO | U1 | 15 |

### 3. Visual Diagrams (`diagram`)
Generate vector graphics of your components.

```bash
# Create a block diagram for U1 and U2
wayricad-python -m extract_pins_plugin diagram --refs "U1,U2" -o schematic.svg board.kicad_pcb
```

### 4. Path Finding (`find-path`)
Find specific signal paths designated by max hops.

```bash
# How does signal get from TP1 to U1?
wayricad-python -m extract_pins_plugin find-path --start "TP1" --end "U1" --max-hops 5 board.kicad_pcb
```

---

# Developer Guide

For contributors who want to understand the codebase structure.

![Program Structure](https://raw.githubusercontent.com/wayri/WayriCAD/main/extract_pins_plugin/Program%20Structure.svg)

---

# FAQ

**Q: Can I run this on KiCAD 8?**
A: The metadata targets KiCAD 9.0+, but it may work on KiCAD 8 if you manually edit the `metadata.json` version requirement, though it is untested.

**Q: Where are the SVG diagrams saved?**
A: By default, they are saved in the same directory as the PCB file.
