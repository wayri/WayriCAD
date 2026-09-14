# Current update: quantitative analytics (0.5)

> **0.6 update:** V6_WORKFLOWS.md, CONTROL_TRUST.md, HOST_ACCEPTANCE.md and the current TEST_REPORT.md describe the new persistent catalog, independent variants, review gates and remaining validation boundaries. The material below retains earlier subsystem details; the current update takes precedence where extended.

For custom price columns, mass/type tables, operating-dissipation breakdowns, unit-aware thresholds, statistics, budgets and CLI/job-set reports, start with **V5_WORKFLOWS.md** and **CLI_REFERENCE.md**. Existing workflows below remain available. The new analytics sample launcher is **TRY_ANALYTICS_SAMPLE_WINDOWS.bat**.

# Version 0.4 workflows

For advanced query/filter management, multi-step bulk recipes, job-set generation and optional bidirectional selection, read V4_WORKFLOWS.md. CLI_REFERENCE.md covers all 21 command families and reviewed writes. Core offline use is unchanged; only live selection needs optional kicad-python. Schematic relay and viewport movement are not host-validated. Ordinary health views remain advisory; release pipelines can enforce chosen gates.

---

# User guide — 0.2.0

For the new column, template, export and Enforce workflows, start with **V2_WORKFLOWS.md**.

## BOM editing

Search matches resolved field values across a component, not only the visible reference. A repeated-sheet part may therefore match another instance's shared internal part number. Use the population filter to focus on fitted, DNP/DNI, BOM-excluded or missing-MPN parts. The table is paginated in groups of 100 and sorts references naturally (R2 before R10).

Select the current page using its header checkbox. Selections are explicit and are retained across pages/filter changes; the selection count tells you the scope. Use the row checkboxes to narrow the selection, then FIT, DNP, DNI or Edit field. Double-click an editable cell for single-part editing. Press Enter on a non-input while parts are selected to open bulk editing. Reference, source, UUID and quantity are derived/read-only.

The row's arrow opens raw values, resolved values, flags, origin labels, source paths and inherited restrictions. Canonical output names such as `InBOM` map to native booleans. Use true/false when editing inclusion flags; their values are not freeform text.

Resetting a base field removes the workspace override. Resetting a named variant explicitly returns that field to the effective default assembly, even when a native or parent-variant differential exists.

## Variants

Create a new variant with a name, description and parent. Names are case-insensitive for uniqueness; Default is reserved. Parent changes flow into descendants unless overridden. Compare two variants for field-level differences. Population matrix shows up to 250 parts and 32 variants at once; full-project output is not limited by that display cap. Click a matrix population cell to edit that instance in that variant.

For a new independent family, derive from Default. A child derived from Economy continues to inherit Economy's sheet restrictions. Native sync flattens these inherited component and sheet differentials into KiCad records, because workspace inheritance is not presumed to be a native KiCad hierarchy.

Delete or rename existing native variants in KiCad, then reopen and reconcile the workspace. A workspace-only variant can be removed if it has no descendants. Deleting a parent cannot silently strand children.

## Variables and aliases

Project variables are shared native text variables. Workspace variables apply only in this tool; named-variant variables layer on top of their inherited context. Variables can reference variables recursively, but cycles, missing names and unresolved expressions block checked exports. Templates can contain expressions such as `${Reference}/${MPN}` as a column source.

Use `${FIELD:MPN}` to explicitly address a symbol field. `${PROJECT:REV}` refers to the effective custom-variable context in this tool, including workspace/variant overrides; it is a WayriCAD expression extension, not a claim about native KiCad syntax. `${R1:MPN}` supports a one-hop reference lookup with the exact stored field name. Arbitrary nested cross-reference chains and every native KiCad built-in are not implemented.

When native sync is needed, avoid WayriCAD-only expressions in schematic fields. Workspace/variant variable definitions are export-only and block sync while nonempty. Project-scope variables are the native-compatible route. Native sync never silently expands local-only variables into fixed text. The exact supported expression subset and any remaining unresolved markers are visible in Checks. Nested/escaped expression grammar and KiCad math are preserved and blocked rather than partly evaluated. See V2_WORKFLOWS.md for generated fields with exact `${NAME}` property keys.

Aliases map alternative supplier/part field names into canonical output fields. Nonempty canonical fields win; a blank canonical field may fall back to a nonempty alias. For example, clearing only MPN will not erase a separate nonempty Manufacturer Part Number field. Alias rules do not rename or delete stored fields.

## CSV import

Choose Import CSV and preview a file or pasted text. A Reference/Designator header is required. Use one reference per row, or a quoted comma-separated reference list. Ranges such as `R1–R8` are intentionally rejected as unknown references rather than expanded ambiguously.

Unmatched references, duplicate assignments, invalid boolean/population values and conflicting shared-sheet base changes block import. Imports target the active variant. Derived quantity, source and identity columns are ignored. All accepted row edits are combined into one undo step.

Supplier feeds generally identify MPN/SKU rather than reference. Join those feeds to the intended reference list externally before importing; this preview does not silently assign a supplier record to every matching MPN across variants. A quoted monetary symbol such as `₹2.50` is not a valid UnitPrice; use numeric `2.50` and separate `INR`.

## Sourcing assumptions

Set boards, spare/attrition percentage, default currency, required fitted-part fields and quote-age threshold. Defaults require MPN and footprint. Missing pricing is a warning and is reported as unpriced; it is not zero. MOQ and order multiples must be positive integers. Different currencies stay separate.

Record alternate candidates, approvals or rejections with reviewer and qualification notes. Approval requires a reviewer and reason but has no identity authentication. It does not change the BOM automatically. Any substitution is an explicit MPN/manufacturer/field edit in the appropriate variant, followed by your engineering review. Footprint changes trigger a release-blocking check until reconciled through a validated native project; that check is not a package-equivalence analyzer.

## Templates and output

Start with Engineering, Assembly, Purchasing, Not fitted, Full audit, Generic ERP CSV, JLCPCB assembly CSV or ASCII engineering report. Use New/Duplicate/Rename/Delete to manage definitions. Add, label, remove or reorder columns, choose group-by fields, sort field, population/exclusion behavior, delimiter and reference compaction. Preview and Export active variant commit the current template form before generating output; the top Save workspace action also commits an edited active template/field-profile form. Share/import JSON transfers definitions without automatically enforcing fields.

Columns not found in the resolved row are blank unless they contain an expression. Grouping is conservative: even a template grouping only by Value cannot merge different MPNs, footprints, prices or exported data values. Prices and quantities are snapshot values, not live workbook formulas. Text that resembles a spreadsheet formula is preserved safely as text.

Checked export refuses release-blocking checks. Explicit draft mode lets you inspect incomplete data while retaining draft status in the filename and metadata where the format supports it. All-variant ZIPs are generated only when every included variant passes, unless Draft was explicitly selected. Each non-default assembly also includes a field-level difference file against Default.

Preview displays at most 100 grouped lines; export includes all lines. The release ZIP is a BOM data handoff, not Gerbers, pick-and-place, PCB STEP files or a complete manufacturing release.

## Keyboard and process lifecycle

Ctrl+S saves the workspace, including active variable/template form edits. Ctrl+Z/Ctrl+Shift+Z undo/redo workspace operations while focus is outside text entry. `/` focuses BOM search. Native dialog Escape closes its dialog. Browser text fields retain normal text-edit shortcuts.

Theme persists in the browser's local storage. Session API authorization stays in session storage. Closing a tab leaves the server process running; Quit or Ctrl+C stops it. Starting the app twice produces independent sessions; source and sidecar hashes guard against accidental overwrite, not against all concurrent engineering conflicts.


## 0.3 direct editing and health

See `V3_WORKFLOWS.md` for the new reviewed spreadsheet-style editor, any-field grouping, consolidation, actual local pad inspection and no-key supplier workflow. Older screenshots/documented modal editing are superseded by the new EDIT review step; native APPLY remains separate.
