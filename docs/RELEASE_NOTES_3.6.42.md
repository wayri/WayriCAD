# WayriCAD 3.6.42

Pin Extractor now helps prepare mating-connector pinouts and matching schematic
labels, with explicit previews before copying.

| Addition | What it does |
|---|---|
| Mating pairs | Review connectors from the current board, another saved board or a proposed mate. Define top/bottom views, added rotation, reflection and relative XY offsets; inspect unique contact pairs and unresolved contacts. |
| Label assignment | Edit A/B naming modifiers, compare existing B nets with proposed names, assign pasted names by exact A pin IDs, and copy either side or selected pairs. |
| CSV / TSV labels | Convert one name column or explicit pin/name columns. Choose numbering, edit individual rows and copy global, local or hierarchical labels with configurable pitch, angle and size. |
| Physical pinout grids | Export actual rows and columns from numbered pad positions, including sparse cells, mirrored views and transposed tables. |
| Automation | New `labels`, `connector-grid` and `connector-mate` CLI commands, with protected inputs and new-file-only exports. |

Open **Pin Extractor → Connector tools** after updating and restarting PCB Editor.
The [workflow guide](../extract_pins_plugin/CONNECTOR_TOOLS.md) is also included
as offline HTML. The main README and plugin help now cover these additions.

## Validation and limits

All 43 native Pin Extractor tests passed, including five UI tests and KiCad
parse/export checks for all three label kinds. Another 28 related CLI,
documentation and plugin-inventory tests passed. Public Marble pin grids were
checked without changing the board; an isolated package CLI check passed.
See the [validation record](audits/CONNECTOR_TOOLS_2026-10-28.md).

Saved-board loading uses a separate native KiCad reader so it also works when
the installed plugin runs through the IPC board adapter. The reader was checked
from an IPC-only parent and does not replace the live working-board context.

The matcher reviews planar contact positions; it does not certify manufacturer
compatibility, keying or 3D fit. Pasted labels must be anchored to the intended
schematic pins or wires. Existing board and schematic nets are not automatically
renamed. Native format parsing passed; interactive Eeschema paste remains
unverified because the desktop automation helper could not initialize.

This release also retains the Quick PI/SI/Therm performance improvements,
guided Joule setup, Blender export and illustrated guides from 3.6.41.
