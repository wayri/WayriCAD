# WayriCAD BOM Studio 0.2 — Columns, exports and field standards

## 1. Three controls that must not be confused

| Control | Where | Changes actual symbol fields? |
|---|---|---|
| Workspace order/visibility | BOM workspace → Columns, or drag a table header | No |
| Export order/inclusion/header | Exports & templates | No |
| Physical property names/defaults | Field name templates → Enforce, then native sync | Only after the separate native confirmation |

Unchecking an export column keeps its definition in the template. Hiding a workspace column keeps the component data. Removing a column definition also leaves component data alone. **Exact enforcement**, not visibility, is the action that can remove custom properties.

## 2. Arrange columns and save layouts

Open **BOM workspace → Columns**. Check the fields to display. Drag rows or use the up/down buttons; checked fields follow that order. Search narrows the chooser, not the data. Show all and Hide all are shortcuts; at least one column must remain selected when applying. Enter a layout name to save a reusable ordered selection. Choosing a saved layout restores its order/visibility. Saved layouts can be shared or deleted from the same dialog. Directly dragging a table header also updates the current workspace layout.

Layouts are in the project sidecar, not browser-only storage. They are independent of export templates and can be shared with other projects using a data-only JSON bundle. The chooser is designed for up to 200 columns, rather than silently accepting an unlimited unusable grid.

## 3. Build and manage a BOM export template

Go to **Exports & templates** and choose a starting template. Use New, Duplicate, Rename or Delete rather than copying a whole project. A name, revision, author and description identify the definition; revisions are metadata, not signed approvals. At least one export template must remain.

Each column has an **Export** checkbox, a source field/expression and an independent output header. Drag or use the arrow buttons to order columns. Unchecked definitions remain available. The header can contain project/active-variant variables, for example `Part number — ${REV}`. Row-dependent header expressions such as `${REFERENCE}` are rejected because a single header cannot represent every component. Duplicate resolved output headers also fail validation.

The **Population & grouping** section controls fitted/all/not-fitted filtering, BOM-excluded components, group-by fields and sort field. Grouping always separates incompatible MPNs, packages, values, population, price/currency and other exported data. Hiding an MPN column does not allow incompatible parts to merge.

The **Text, variables & export options** section selects resolved or raw field values, CSV delimiter, UTF-8 with/without BOM, ASCII or Windows-1252 encoding, CRLF/LF newlines, minimal/all-cell quoting, reference/range separators and plain-text column width. Raw mode preserves physical variable expressions even through a configured alias such as Manufacturer Part Number → MPN. Derived quantities/reference groups remain computed. Virtual expression columns are calculations and still evaluate.

**Preview** and **Export active variant** save the current template form into the workspace before generating output. Save workspace persists it to disk. **Use these columns in workspace** copies the included non-virtual columns into the separate GUI layout.

## 4. Export formats

| Format | Extension | Intended use / boundary |
|---|---|---|
| CSV | `.csv` | Purchasing, assembler and ERP import; configurable delimiter/encoding/newlines/quoting |
| TSV | `.tsv` | Tab-delimited spreadsheets and data pipelines; encoding/newline controls |
| Excel | `.xlsx` | Styled BOM plus release notes/checks; snapshot quantities and costs, not live pricing/formulas |
| OpenDocument | `.ods` | Basic ODF 1.2 spreadsheet package; text cells, no macros/formulas |
| Unicode text | `.txt` | Fixed-width, wrapped UTF-8 report |
| ASCII text | `.asc` | 7-bit report; non-ASCII escaped explicitly or rejected |
| Generic BOM XML | `.xml` | Documented `wayricad-bom-1` structure; custom labels retained |
| JSON | `.json` | Structured BOM, metadata and checks |
| JSON Lines | `.jsonl` | One metadata record, then one BOM-line record per line |
| Markdown | `.md` | Documentation and Git review tables |
| HTML | `.html` | Standalone printable report; browser Print/Save to PDF remains a browser action |
| Release bundle | `.zip` | Every variant in CSV, XLSX, HTML, JSON, TXT and XML, with differences, checks, workspace snapshot and SHA-256 manifest |

The ASCII exporter uses `\xHH`, `\uXXXX` or `\UXXXXXXXX` character escapes rather than quietly stripping symbols such as µ, Ω or currency characters. Strict mode refuses unrepresentable text. Long values wrap instead of being truncated. Use a hyphen range separator for a conventional `R1-R3` ASCII reference range. Fixed-width reports are human-readable handoffs, **not a byte-for-byte reversible serialization**; use JSON/raw mode when that is needed. Report width is a per-column character cap, not an 80-column machine format. Control characters are visibly escaped in reports.

CSV/TSV prefixes that could be interpreted as spreadsheet formulas are escaped. XLSX and ODS store supplied text as strings and contain no user-supplied executable formula or macro. This can intentionally alter a CSV cell's leading text for safety; use raw JSON when the exact original string is required. ODS is a basic interchange workbook, not an imported office-document template with arbitrary styling/layout fidelity.

**Generic ERP CSV** is a starter column mapping, not an authenticated ERP connector. **JLCPCB assembly CSV** maps Comment, Designator, Footprint and LCSC Part # and recognizes common LCSC/JLCPCB field aliases. Populate valid supplier codes and check the chosen assembler's current requirements; this profile is not an assembly-acceptance certificate. It does not generate centroid/CPL files. This package does not claim native IPC-2581, ODB++, IPC-1752, proprietary Xpedition exchange, or KiCad XML-netlist conformance for its generic BOM XML.

## 5. Share templates without sharing a whole design

Share JSON exports the selected export template, field profile or saved layout. **Share all templates** exports the catalog definitions together. Import previews what will be added, replaced, skipped or renamed. Select Keep both, Replace or Skip for name collisions. Future/unknown bundle versions, duplicate JSON keys, executable/unknown definition options, malformed fields and unsafe reserved keys are rejected. Bundles are capped at 2 MiB and 100 records per section.

A bundle does not implicitly include component rows, source paths, variant definitions or project-variable values. **Literal defaults, labels, descriptions and author names may still contain proprietary data**; inspect before sharing. Variables referenced by a shared template must be defined in its destination project. Importing a field profile only stores a definition; it never enforces or writes native files automatically.

A ready-to-import demonstration bundle is in `examples/template_bundles/Team_Standard.wayricad-bom-templates.json`. It contains no project data or secret variable definitions. These are schema/mapping templates, not arbitrary user-uploaded `.xlsx` layouts.

## 6. Define a field-name standard

Open **Field name templates → New**. Add custom field names in the desired order. For each field, set aliases to normalize, an optional default/value expression, Required in fitted BOM, Visible on schematic, and URL-field metadata for native project defaults. Mandatory identity/value/footprint/datasheet fields and reserved simulation metadata are protected rather than offered as deletable template rows. Native DNP, BOM, placement, board and simulation flags remain independent.

Ordinary name case is normalized: `mpn` can become `MPN`. Variable tokens are never case-folded. Aliases with different nonempty raw values block enforcement instead of picking a winner. Even two expressions that currently resolve to the same text remain a conflict when their raw expressions differ; their future behavior could differ.

Defaults apply to missing fields. Preserve, Fill and Reset control how existing fields are treated. New fields use their template visibility; existing positions, styles and visibility are preserved unless **Also apply template visibility to existing schematic fields** is selected. New visible fields start at the symbol anchor; arrange/autoplace them in KiCad as needed. Field ordering is written in native property order, but a KiCad editor may apply its own display ordering.

## 7. Enforce with a complete review

Choose **Enforce…**. The defaults are Merge, Preserve existing values, Preserve raw field-name expressions, Preserve value expressions and Register native project field-name defaults. Existing schematic visibility is not reset by default.

**Merge** adds/migrates template fields while retaining other custom fields. **Exact** also removes non-template custom properties and, when registration is enabled, extra native field-name defaults. **Fill** fills blank values; **Reset** replaces template-field values with defaults. Baking names and values are two independent destructive choices; generated fields have the special rule below.

Preview covers all supported component instances, sheets and named variants, not only selected/visible rows. It lists additions, case/alias renames, removals, overwrites, order and visibility changes, native-default changes and variable-expression losses. The on-screen list is capped at 400 events; **Download full review** contains every event. Conflicts, unresolved expressions, name collisions, deleted cross-reference targets and incompatible shared-sheet changes block staging. A new edit or source-file change invalidates the review.

After reviewing, type `ENFORCE`. Destructive plans also require the explicit loss acknowledgement. This creates one undoable workspace operation; it does **not** write `.kicad_sch`/`.kicad_pro`. Parent/child variant inheritance continues for values that were inherited before enforcement. Save workspace retains the staged schema. Undo restores the pre-enforcement state in the current session.

For native changes, open **Review & native sync**, generate a fresh native diff, close every KiCad editor, acknowledge that closure and type `APPLY`. Original bytes are backed up. The result is checked through this tool's adapter, including exact default-field membership and all variant raw values/flags. A successful adapter reload is not a real KiCad-host validation. Reopen the files in KiCad, inspect them and update the PCB from the schematic yourself.

Native registration writes `schematic.drawing.field_names` in **this project's** `.kicad_pro`. It does not modify global Preferences or rewrite installed symbol libraries. It stores field names/visible/URL defaults, **not custom value defaults or required-field policies**; those remain WayriCAD profile rules and apply when you enforce again. It is not a continuously running native constraint on symbols placed later. Share/import the profile in other projects and enforce there deliberately.

## 8. KiCad variables in names and values

Ordinary property values may contain `${REV}`, `${PART_CODE}`, field references, supported sheet variables and the documented subset of built-ins. Keep raw text in the sidecar/native fields; resolved exports do not replace it. Project-variable definitions are never deleted by enforcement.

For a compound physical name such as `Code_${TYPE}` with value `${PART_CODE}`, both raw expressions can be kept and inspected. WayriCAD also exposes a resolved-name alias in its grid/export engine. Native storage retains the original key. The native editor's own shown-name behavior is not replaced or guaranteed by that alias.

An **exact word-variable name** such as `${REV}` is a **generated KiCad field**. KiCad locks its value to the same `${REV}` expression and displays `REV` as its shown name. In the field profile, leave the default blank or identical to that expression. Generated value editing is blocked; edit the underlying project variable instead. A distinct default, contradictory imported value, or baking only its value while keeping the generated name is rejected. Explicitly baking/renaming the field to an ordinary literal name is allowed after review and loss acknowledgement.

A **virtual BOM column** is different: `${SYMBOL_LIBRARY}:${SYMBOL_NAME}`, `${QUANTITY}` and `${ITEM_NUMBER}` are evaluated for output without adding a property to every symbol. Group quantities and row numbers are evaluated after grouping. Header expressions are resolved once in project/variant context.

The resolver is not the full KiCad expression interpreter. Unknown built-ins, cycles, malformed expressions, nested variable-name grammar, escaped expression grammar and `@{...}` math are preserved and reported as errors; checked output/enforcement is blocked rather than publishing a plausible wrong result. Arbitrary environment expansion, every drawing-sheet context and recursive cross-symbol chains are not claimed. Project, ordinary recursively referenced variables, supported field/sheet context, one-hop exact-reference lookups and common symbol built-ins are covered. WayriCAD-only `${PROJECT:...}` / `${FIELD:...}` and workspace/variant-only variable definitions remain export-only and block native synchronization while used.

## 9. Limitations and release responsibility

This release remains a developer preview. There is no automatic cloud supplier lookup, ERP/PLM connection, authenticated multi-user approval, entire-computer enforcement, PCB library rewrite or proven KiCad 11 support. Local file hashes cannot detect unsaved editor memory. Multi-file writes are recoverable with backups but are not atomic against power loss. Review the compatibility and test reports before using real designs.
