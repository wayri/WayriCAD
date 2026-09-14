# WayriCAD BOM Studio 0.8.3 — Integrated assembler exports

This is part of the **full PCM plugin**, not a profile pack to merge by hand. The previous 0.8.2 distributor export and all earlier engineering workspaces remain available. Installation is through KiCad Manager → Plugin and Content Manager → Install from File using the complete ZIP.

## Separate manufacturing and purchasing quantities

**Vendor split & upload** remains the distributor/purchasing view: it can include board counts, attrition, MOQ and order multiples.

**OEM / assembly export** is the new assembly view. Every selected profile describes the **same ONE board**, with quantities equal to the number of explicit reference designators. Existing board counts, attrition, MOQ, order multiples, supplier routing and purchasing overrides are never applied. Several selected assemblers are alternative handoffs/quotations of the same design, not a split order or extra demand.

On the assembler website enter the actual number of boards separately and confirm how that portal interprets its quantity fields. Do not upload multiple formats or alternative vendor folders as cumulative orders. Choosing an assembler does not change KiCad template authority, component fields or distributor assignments.

## Built-in profiles and verification level

| Profile | Included mapping | Basis / limit |
|---|---|---|
| JLCPCB | Comment, Designator, Footprint, LCSC Part # | Required field names are documented; LCSC code optional. Four-column output, without a fabricated Quantity column. Quantities come from designator lists. |
| PCBWay | Item, Quantity, Reference(s), Value, Footprint, Manufacturer, Manufacturer Part Number, Description | Editable review-required mapping; not a verified clone of the current portal workbook. |
| HQPCB | Designator, Quantity, Description, Package, Manufacturer, Manufacturer Part Number | Separate from NextPCB. Current official template could not be verified. Review required. |
| NextPCB | Comment, Designator, Footprint, Quantity, Manufacturer, Manufacturer Part Number | Editable review-required mapping. Official site advertises spreadsheet/CSV upload, but these exact headings are not claimed as a validated current workbook template. |
| Sierra Circuits | Quantity per board, Manufacturer Part Number, Reference Designators, DNI/DNP, Value, Size/Footprint, Part Description, Manufacturer | Based on Sierra's published BOM field list. Fitted-only output; excluded parts are in the audit. |
| PCB Power | MPN, Quantity, Reference Designator, Manufacturer Name, Description, Footprint | PowerBoM documents its mandatory mapped fields. Verify scope and supply mode during upload. |
| Seeed Fusion | Designator, Comment, Footprint, Quantity, Manufacturer, Manufacturer Part Number | Editable review-required mapping; OPL codes are not inferred. |
| Generic assembler | Reference Designators, Quantity per board, Value, Footprint, Manufacturer, Manufacturer Part Number, Description | Agree the columns with the receiving assembler. Review required. |

“Documented field mapping” means names/semantics informed by published documentation, **not** provider certification or an authenticated portal-import test. All production portal imports remain untested. Custom headers/order are marked review-required. TSV output also requires review because importer support is not established. Legacy binary `.xls` is not generated; Excel means `.xlsx`.

## GUI: preview → review → export

Open a saved project, choose its intended variant, then **OEM / assembly export**. Check one or more providers. No profile import is required. Expand **Map component properties and supplier codes** to use exact project properties for Value, Comment, Description, Footprint, manufacturer, MPN or internal number. An explicit mapping preserves an intentionally blank property; it does not fall through to another alias. Auto Comment/Description can fall back to Value, with provenance recorded. Full descriptions are used where supplied.

JLCPCB looks only at configured or LCSC/JLCPCB-specific properties. A generic DigiKey/Mouser SKU is not mistaken for an LCSC code. A supplied code must be an exact `C` followed by digits. Blank codes require website manual part matching; the optional **Require a supplied JLCPCB/LCSC code** policy blocks missing codes. This does not authenticate that a code describes the intended part.

Choose full `Library:Footprint` text or explicitly remove the library nickname only. No land-pattern dimensions or generic package names are inferred. Original links and properties remain unchanged. Map a dedicated package property when your assembler needs a different designation.

**Preview assembly BOMs** shows per-board counts, excluded records, each provider's actual column headings and rows, source checks, profile warnings and full JSON review. Provider notes use text labels and tooltips in addition to colors. Required/unverified/custom mappings need the explicit review acknowledgement before binary export. Changing profile selection or custom columns clears that acknowledgement. Relevant settings, data or sources invalidate the prior preview.

**Customize headers / column order** edits the selected profile (or first checked profile before preview). Move columns with arrows, change headings, add supported sources or remove optional columns. Required reference, part-identity, package and per-board-quantity fields cannot be removed. JLCPCB's short default deliberately lacks a Quantity column. Column changes affect output only, never native field names.

**Export assembler ZIP** writes all selected alternatives. The active provider also has separate CSV / Excel / TSV actions. A single-file CLI export requires one selected provider; ZIP carries multiple providers. Binary exports are refused for missing/conflicting required data, global source errors or unacknowledged mappings. There is no silently partial assembly BOM.

The whole committed variant is used, not the grid's visible page/search/checkbox selection. Native DNP/DNI, BOM-excluded and off-board parts do not create assembly demand. `in_pos_files=false` alone does not remove a fitted part from the BOM (for example, manually assembled parts). Repeated physical instances remain separate; quantities are not counts of graphical symbol units. Unknown rule-area population remains blocked by the existing source safeguards.

## Files

```
uploads/jlcpcb/jlcpcb_BOM_PER_BOARD.csv
uploads/jlcpcb/jlcpcb_BOM_PER_BOARD.xlsx
uploads/pcbway/pcbway_BOM_PER_BOARD.csv
uploads/nextpcb/nextpcb_BOM_PER_BOARD.xlsx
... selected profiles and formats ...
reports/REPORT.json
reports/EXCLUDED.csv
README_UPLOAD.txt
manifest.json
```

CSV uses UTF-8 with BOM, correct quoting and CRLF; TSV is an explicit alternative. XLSX has exactly one `BOM` worksheet, headers in row 1, text identifiers and numeric quantity/item cells, without formulas/macros or decorative title/report sheets. No cell is silently truncated. Oversized reference lists fail rather than losing designators. Upload files do not include the broader private audit. ZIPs contain per-file hashes; hashes are not signatures or manufacturing approval.

Exported files may contain confidential MPNs/references. Review before sharing/uploading. All-excluded variants create **NO_ASSEMBLY_DEMAND** audit-only ZIPs, not empty purported manufacturing requests. Only files in `uploads/` are BOM handoffs, and CSV/XLSX/TSV are alternative representations of the same quantities.

This feature generates no CPL/pick-and-place coordinates, rotations, side, Gerbers, drill files or assembly drawings. Generate a matching placement/manufacturing package separately. There is no live stock or price lookup, automatic upload, supplier authentication, purchasing authorization or ordering.

## Save and share

**Save assembly settings** stages an undoable sidecar update. **Save workspace** persists it and also commits pending assembly mapping drafts. Import/shared settings use `wayricad-assembler-config-1`, separate from both vendor profiles and field-name-template enforcement. Import does not alter component properties and resets the acknowledgement. The previous standalone assembler profile pack is not needed and should not be imported into this new schema. Keep existing distributor configurations unchanged.

The reusable source mappings, output overrides and provider selection remain in `assembler_export_settings` in the existing sidecar. Back up before downgrading to an older plugin.

## CLI and job-set pipelines

From the installed `org_wayricad_bomstudio` directory:

```powershell
py -3 .\cli.py assemblers --list-profiles
py -3 .\cli.py assemblers "C:\Projects\Board\Board.kicad_pro" --profile jlcpcb --format xlsx --output ".\JLCPCB_BOM.xlsx"
py -3 .\cli.py assemblers "C:\Projects\Board\Board.kicad_pro" --profile nextpcb --acknowledge-profile-review --format csv --output ".\NextPCB_BOM.csv"
py -3 .\cli.py assemblers "C:\Projects\Board\Board.kicad_pro" --all-profiles --acknowledge-profile-review --format zip --output ".\Assembler_BOMs.zip"
```

Use new output paths; nothing is overwritten. `--config FILE` or `--config -` reads the same data-only settings. Repeat `--profile` for several choices. `--fields` is not used: individual mappings have `--mpn-field`, `--manufacturer-field`, `--description-field`, `--value-field`, `--comment-field`, `--footprint-field` and `--customer-field`. `--footprint-mode name` is an explicit output change. Configure a per-provider SKU property in JSON under `sku_fields`. `--variant` selects a named native or in-program BOM-only variant; raw source protections remain.

Default JSON preview uses exit code 3 for BLOCKED or REVIEW_REQUIRED and still emits the report. Failed binary output emits diagnostics and creates no file. `--fingerprint` binds output to the preceding review. `--save-settings` is an explicit sidecar write restricted to JSON/stdout with no `--source-only` or named output. Merely inspecting or exporting never saves native files or settings.

There are now 39 command families. Existing CLI/job sets continue to work. A pipeline may add `"assembler_exports": { ... assembler config ... }`. Omit/null leaves earlier behavior unchanged. The step writes `assembler-review.json` per variant; blocked/unreviewed mappings fail the entire pipeline. Normal BOM and assembly upload files are published only when all configured gates pass. Job sets reuse the existing runner; they do not acquire a separate interpretation of quantities. `examples/assembler_exports/pipeline-assemblers.json` is advisory except for its ordinary checks and complete, reviewed assembly handoff requirements.

## Sources checked 10 September 2026

- JLCPCB: https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly
- Sierra Circuits: https://www.protoexpress.com/kb/pcb-bom-file/
- PCB Power PowerBoM: https://www.pcbpower.com/blog-detail/introducing-a-smart-tool-powerbom-how-to-use-it-a-step-by-step-guide
- NextPCB format support: https://www.nextpcb.com/
- PCBWay: https://www.pcbway.com/ (current exact template not verified)
- HQPCB: https://www.hqpcb.com/ (current template unavailable)
- Seeed: https://www.seeedstudio.com/fusion_pcb.html (current exact template not verified)

Use the current recipient's template/column mapping if their portal changes. See TEST_REPORT.md for actual tested execution and unexecuted host/portal boundaries.
