# Connector mating, pin tables and schematic labels

Open **Pin Extractor → Connector tools**. Its three pages share a read-only
workflow: choose inputs, review the preview, then copy the result. These tools
do not move components, change PCB nets or rename schematic symbols.

Availability: included in WayriCAD 3.6.42.

| Page | Start with | Result |
|---|---|---|
| Mating pair | Two connector pin layouts and their reviewed positions/orientations | A pin-to-pin table and matching label sets for connector A and B |
| Paste labels | One label column or explicit pin/label columns | Editable label rows and native KiCad clipboard labels |
| Physical pinout | A footprint with numbered pad positions | A row/column table preserving the connector's physical arrangement |

## Review a mating pair

1. Choose connector **A** from the working board. Choose **B** from the board or
   load a separate saved board as a read-only source. If B is a proposed copy
   of A's geometry, review its contact numbering against the actual mating part.
2. Define the board side, rotation, explicit reflection and relative XY offsets
   for each connector. Start with pin 1 and one asymmetric contact or key so that
   two visually plausible orientations cannot be confused.
3. Build the preview. Check the two views and the **A pin → B pin** assignment.
   Geometric matching accepts only unique reciprocal contacts within the chosen
   distance tolerance. Unmatched, coincident or ambiguous contacts stay visible.
4. Review the labels row by row. Use the same names on both sides, or select/add
   prefixes, suffixes and a template for each side's naming convention. Copy all
   reviewed rows or select individual rows for a smaller copy.
5. Paste the copied native labels into Schematic Editor and place their anchors
   on the intended pins or wires. Compare both schematics with the pin-to-pin
   table before using the result for a board update or harness definition.

To assign a pasted pin/name list to the pair in bulk, preview it on **Paste
labels**, return to **Mating pair**, and choose **Assign pasted names to pair**.
The assignment uses exact A pin IDs; unknown IDs reject the entire assignment.
Existing B nets remain visible beside the proposed B labels. The board's nets
are not renamed. You can edit individual proposed names before copying.

### Coordinate convention

The source coordinates are numbered pad centres in a **board-top XY view**, in
millimetres. A pose centres the connector's pad bounding box, reflects X for a
bottom-side view, applies any additional explicit X reflection, rotates, then
adds the relative XY offsets. KiCad Y increases down the screen, so a positive
mathematical rotation appears clockwise in this view. The offsets are relative
to the centred connector, not a command to move a footprint on the board.
The original footprint rotation is already present in the source coordinates;
the angle control adds to that orientation. The `{ref}` template token uses
`MATE` for a proposed mate without an existing footprint reference.

The default B reflection is a visible starting convention, not a manufacturer's
pinout rule. Bottom-side selection and the additional reflection can cancel
each other. Review the preview rather than assuming that equal pin numbers mate.
The model checks planar contact-centre correspondence. It does not prove mating
height, keying, mechanical clearance, manufacturer compatibility or 3D fit.

**Load B board** runs in a separate native KiCad Python reader, including when
the main window uses the IPC board adapter. The original live board remains the
source for A. A missing native runtime produces setup guidance; the other tabs
remain usable during the read. Source hashes are checked before accepting or
copying its contacts. The reader bounds an external inventory to 20,000
footprints and 200,000 numbered contacts; a larger design needs a smaller
review source. Per-footprint invalid padstacks stay visible as diagnostics.

## Paste CSV or a column of names

For a single column, choose **Labels** and a numbering sequence:

```text
SCL
SDA
GND
3V3
```

For explicit assignment, choose **Pin + label**:

```csv
1,SCL
2,SDA
A3,GND
A4,3V3
```

CSV quoting is supported; TSV from a spreadsheet and semicolon-separated data
are accepted. Select **Header** only when the first record is a header. Auto
mode distinguishes the record width; it does not silently discard a name that
looks like a header. Pin IDs can be alphanumeric. Duplicate pin IDs and invalid
rows need correction before copying.

| Control | Meaning |
|---|---|
| Start / step | Numbering for a one-column list; explicit two-column pin IDs are retained |
| Sequential / row-major | Assign generated numbers in list order |
| Column-major | Reorder generated numbers by the chosen logical column count |
| Odd-even | Assign odd numeric pin IDs first, then even numeric IDs |
| Serpentine | Alternate the generated numbering direction on successive logical rows |
| Prefix / suffix | Add literal text around the formatted name |
| Template | Combine `{label}`, `{pin}` and `{ref}` without running code |
| Case | Retain, uppercase or lowercase the result |
| Label kind | Global, local or hierarchical KiCad labels |
| Label orientation | 0°, 90°, 180° or 270° at the schematic anchor |
| Pitch / text size | Clipboard anchor spacing and label text size, in mm |

Edit individual labels in the preview table after the bulk conversion. Select
rows to copy just those rows; use the bulk action for the complete reviewed
set. An explicit pin list may be supplied by a connector workflow rather than
generated numbering.

The pin-number column is an assignment aid. A schematic label itself does not
carry an electrical connector-pin number. The connection is established when
its anchor is placed on the intended symbol pin or wire. Clipboard pitch is
independent of the PCB pad pitch and should match the schematic's pin spacing.

### Label scope and repeated names

- **Global** labels of the same name connect throughout a schematic project.
  Pasting A and B into the same project with matching global names intentionally
  connects them electrically, even if they are drawn apart.
- **Local** labels connect matching names within their schematic sheet.
- **Hierarchical** labels require corresponding sheet pins and hierarchy
  connections. Copying a label does not create or update those sheet pins.

Repeated names such as GND are valid and join that net according to the selected
scope. Use modifiers deliberately when a copied block should remain isolated.
Generated global and hierarchical labels use the bidirectional shape; they do
not infer signal direction from connector pins.

### Native format and validation scope

The clipboard export contains label objects with fresh UUIDs. KiCad 10.0.6's
[schematic parser](https://github.com/KiCad/kicad-source-mirror/blob/10.0.6/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_parser.cpp)
accepts an object stream in its copyable-only branch. The same generated global,
local and hierarchical objects were wrapped in new schematics and parsed/exported
by the installed KiCad CLI. An interactive Eeschema paste was not validated in
this session; native file parsing and actual clipboard interaction are separate
checks.

## Extract the actual rows and columns

Choose a footprint on **Physical pinout**, then choose top/bottom view,
rotation and optional reflection. The table clusters numbered pad centres using
the selected tolerance. It retains empty positions, pin numbers and net names;
it does not sort the table back into numeric order. Transpose exchanges table
rows and columns when a column-oriented document is preferable.

Use this for dual-row headers, multi-column connectors and sparse grids. An
irregular connector can produce a sparse table. Collisions, excessive grid
size, or duplicate-number pads at different positions are reported rather than
silently assigned to a made-up cell. Unnumbered mechanical pads are excluded.

The existing **Connector Preview** remains a readable pin-order report. The
new **Physical pinout** page is the geometry-based arrangement.

## Command line

Use the suite CLI installation, or run `python -m extract_pins_plugin.cli` from
the source checkout. Boardless label conversion and mating JSON run in ordinary
Python. Saved-board extraction needs KiCad's native `pcbnew` runtime. Run each
command with `--help` for all options. File exports require a new path; native
design paths, existing files and input-file replacement are refused.

### CSV to pasteable global labels

```text
wayricad labels C:/Projects/Example/pins.csv --columns pin-label --header --kind global --pitch 2.54 --output C:/Projects/Example/labels.txt
wayricad labels C:/Projects/Example/names.csv --columns labels --sequence odd-even --prefix IO_ --format csv
wayricad labels C:/Projects/Example/pins.csv --columns pin-label --select 1,A3 --kind local
```

The default output is native schematic clipboard text. Copy the text itself to
the clipboard, then paste in KiCad. `--format csv` or `--format json` produces
an assignment table instead. `-` reads the input from stdin. `--header` is opt-in.

### Physical connector table

```text
wayricad connector-grid C:/Projects/Example/board.kicad_pcb --ref J2 --side bottom --rotation 90 --format csv --output C:/Projects/Example/J2-physical.csv
wayricad connector-grid C:/Projects/Example/board.kicad_pcb --ref J2 --transpose --format md
```

The clustering tolerance defaults to 0.02 mm and is set with `--tolerance`.
This command reads the saved board; it cannot include unsaved editor changes.

### Explicit mating review

Save the following input as `mate.json` in an example folder:

```json
{
  "a": [
    {"pin": "1", "label": "SCL", "x_mm": -1, "y_mm": 0},
    {"pin": "2", "label": "GND", "x_mm": 1, "y_mm": 0}
  ],
  "b": [
    {"pin": "1", "label": "", "x_mm": -1, "y_mm": 0},
    {"pin": "2", "label": "", "x_mm": 1, "y_mm": 0}
  ],
  "pose_a": {"side": "top", "rotation_deg": 0},
  "pose_b": {"side": "bottom", "rotation_deg": 0, "mirror": false}
}
```

In this explicitly mirrored two-contact example, A1 matches B2 and A2 matches
B1. That illustrates the pose transform; it is not a general connector rule.

```text
wayricad connector-mate C:/Projects/Example/mate.json --format json
wayricad connector-mate C:/Projects/Example/mate.json --format clipboard-b --kind global --output C:/Projects/Example/B-labels.txt
wayricad connector-mate C:/Projects/Example/mate.json --a-prefix HOST_ --b-prefix CARD_ --format csv
```

`--labels-from a` is the default. Use `--labels-from b` when B owns the reviewed
signal names. Prefixes/suffixes are independent for A and B. `--format
clipboard-pair` creates two separated label groups; matching global names in
one project still connect. JSON includes the poses, matched contact distances,
unmatched contacts and issues.

A complete, unambiguous mapping returns exit code 0. A JSON/CSV review with
unresolved contacts returns 3 while retaining its diagnostics. Clipboard output
is refused in that state unless `--allow-partial` explicitly selects the valid
matched subset. Invalid input or a protected output path returns 2. No command
rewrites a PCB or schematic.
