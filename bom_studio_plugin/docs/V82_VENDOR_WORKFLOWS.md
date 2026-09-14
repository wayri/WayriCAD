# WayriCAD BOM Studio 0.8.2 — Vendor split and upload handoff

This is an explicit purchasing tool, independent of the default KiCad BOM format. It does not change field-name templates, native properties, the active BOM authority, stock, orders or inventory. No supplier calls, credentials or uploads occur during calculation/export.

## GUI workflow

Open **Vendor split & upload** in the navigation. Choose the actual property containing your preferred vendor, e.g. `Supplier`, `Vendor`, `Distributor`, or a custom name. Blank mapping uses conflict-checked aliases. An explicit mapping preserves an intentionally blank property rather than falling through to a different alias. The profile can map exact physical MPN, manufacturer, generic supplier SKU, customer/internal number, MOQ and order-multiple fields. Raw variables stay in source properties; supported resolved values are used for export.

Enter board count/attrition, or leave them blank to use workspace build settings. Choose upload quantity basis: Installed, Required or Order. The default is Order. Run **Preview vendor split**. The full active variant is considered, independent of the grid's visible page/search/selection. Native DNP/DNI and BOM-excluded items do not create demand; excluded rows remain in a separate report.

Tabs show each vendor's upload lines, All eligible, Unassigned/blocked and Excluded. All eligible/Unassigned tabs have routing checkboxes independent of BOM edit-selection checkboxes. Select rows and **Assign vendor** to route their entire demand to one distributor. A single row can also receive a reviewed vendor-SKU override. These overrides are variant-scoped and bind to the row's current part/flag signature. Changed properties make a saved override stale instead of silently assigning a changed part. Delete/reset stale assignments or review and assign them again.

Generic old-vendor SKUs are not reused after a vendor change. A new vendor-specific property or explicit override can supply that vendor's SKU. Other vendors' SKU columns are ignored. A blank SKU is allowed only with a usable full manufacturer part number and an output column that carries it. Value/footprint alone are never orderable identifiers. Global BOM/source errors still block uploads, even when a mapping is explicit.

**Save mappings to workspace** stages an undoable sidecar configuration change. **Save workspace** persists it. Top-level Save also commits a pending vendor mapping/routing draft, even after navigating away. Mapping/profile drafts survive navigation; changing settings or source data invalidates the old preview. Native files are never written by this workflow. Save a backup before downgrading an updated sidecar to an older plugin.

## Distributor profiles and files

Built-in names/aliases normalize common DigiKey and Mouser spellings. A field containing several choices, such as `DigiKey / Mouser`, is unresolved until deliberately assigned. Unknown single vendor names get their own explicitly generic profile rather than being routed to a known distributor by a partial-name guess.

| Profile | Default headings |
|---|---|
| DigiKey | DigiKey Part Number; Manufacturer Part Number; Quantity; Customer Reference |
| Mouser | Mouser Part Number; Manufacturer Part Number; Quantity 1; Customer Part Number |
| Generic vendor | Supplier Part Number; Manufacturer Part Number; Manufacturer; Quantity; Customer Part Number; References |

Choose CSV and/or XLSX, with optional TSV. CSV is UTF-8 with BOM and CRLF, correctly quoting delimiters. XLSX has **one BOM worksheet**, headings in row 1, no title/banner/checks sheets, no formulas/macros, text MPN/SKU cells and numeric quantity cells. Leading zeroes and complete ordering suffixes are retained. Formula-like or control-bearing upload identifiers are refused, not escaped into a different purchasable identity. Private audit CSV has spreadsheet-formula prefix protection; do not upload the audit.

Use **Vendor profiles & column mapping** to override built-ins or add a supplier-specific mapping. Allowed keys are `name`, `aliases`, `sku_fields`, `headers`, `keys`, `max_lines`, and optional HTTPS `url`. Column keys include `sku`, `mpn`, `manufacturer`, `upload_qty`, `customer_reference`, `references`, `value`, `footprint`, `installed_qty`, `required_qty`, `order_qty`, and `overbuy_qty`. Require at least one identity column and `upload_qty`. Share/import data-only JSON; sharing excludes project-specific routing assignments. Profile literals can still contain proprietary information.

Example custom profile (under the configuration's `profiles` object):

```json
{
  "local": {
    "name": "Local supplier",
    "aliases": ["Local Components"],
    "sku_fields": ["Local SKU"],
    "headers": ["Part Number", "Quantity", "Customer Reference"],
    "keys": ["mpn", "upload_qty", "customer_reference"],
    "max_lines": 500
  }
}
```

DigiKey/Mouser profiles target their documented BOM upload/column-mapping workflow. Website templates, limits and regional/account behavior can change; map headings when prompted. This release has **not** uploaded a file to an authenticated production distributor account. Generic/TSV mappings require importer support and are not declared universal compatibility. CSV or XLSX is the primary handoff.

## Quantity accounting — all numbers are component pieces

For each compatible pooled identity:

```
installed = physical occurrences × boards
required = ceil(installed × (1 + attrition_percent / 100))
order = ceil(max(required, MOQ) / order_multiple) × order_multiple
attrition = required - installed
overbuy = order - required
```

Blank MOQ/multiple means 1; supplied malformed or zero policy data is blocked. Pooling separates vendor, full MPN/manufacturer/SKU, value, footprint, internal/customer number, order policies and recorded rating/packaging constraints. Missing manufacturer/MPN identities are not optimistically merged. One vendor SKU with contradictory manufacturer/MPN identities blocks both lines. The reference list is retained; long lists without an internal number get a deterministic `KW-...` customer marker with the complete list in the master audit.

The summary reconciles routed plus unresolved demand against every eligible physical occurrence. All-excluded variants produce **NO_PURCHASING_DEMAND** audit-only ZIPs, not empty purported orders. Entered prices and live stock are not part of this calculation. Existing pricing/health/buildplan tools remain separate. This view routes each occurrence to one vendor; fractional/split quantities for the same occurrence, supplier optimization, inventory deduction, quote discovery and auto-ordering are not implemented here.

## Upload the right file exactly once

**Export vendor ZIP** produces:

```
uploads/DigiKey__digikey.csv
uploads/DigiKey__digikey.xlsx
uploads/Mouser__mouser.csv
uploads/Mouser__mouser.xlsx
reports/MASTER_ROUTING.csv
reports/UNASSIGNED.csv
reports/EXCLUDED.csv
reports/REPORT.json
README_UPLOAD.txt
manifest.json
```

File chunking is configurable. Convenience defaults: DigiKey 1000 lines, Mouser 200, generic 1000. These are not guarantees of current account limits. Chunks include `001-of-...` in filenames. A single-file action refuses a multi-file result rather than truncating it. Every file is hashed in the package manifest (except that manifest itself).

Upload **only** files from `uploads/`. CSV/XLSX/TSV for one vendor/chunk encode the **same demand**: upload one format, not all alternatives. On the website, set assembly multiplier to **1** and additional attrition to **0** because selected allowances/build quantities are already included. Verify the exact full MPN, manufacturer, distributor SKU, reel/cut-tape packaging, price, current stock and actual cart quantity. A file is a request for matching/review, not a reservation or authorization.

Unassigned/blocked rows prevent complete upload export. Deliberately checking **PARTIAL** enables a ZIP with PARTIAL-labelled upload filenames and the unresolved-parts report. Partial handoffs are ZIP-only so the companion audit is retained. No safely routed demand means no partial upload. Partial mode cannot bypass schematic rule-area uncertainty, source drift, unresolved expressions or other global BOM-data errors. The existing native-engine export route remains separate; this tool does not falsely validate rule-area-derived population.

Reports/configuration can expose source paths, internal numbers, vendor choices, part metadata and reference lists. Review before sharing. The upload subset deliberately omits the broader audit, prices and private geometry.

## CLI and job sets

There are **38 command families**, including the new `vendors`. From the installed plugin directory:

```powershell
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --vendor-field Supplier --boards 20 --format json --output ".\routing-review.json"
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --vendor-field Supplier --boards 20 --format zip --output ".\vendor-boms.zip"
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --format xlsx --vendor mouser --output ".\Mouser.xlsx"
```

`--config FILE` or `--config -` accepts the same data-only configuration. Optional `--fingerprint` requires the exact preceding review. `--allow-partial` is explicit and binary partial handoffs require ZIP. `--save-settings` deliberately saves the mapping in the sidecar and is incompatible with `--source-only` or binary/file output. Ordinary reads/exports never save. A vendor JSON preview exits 3 on blocked/incomplete demand unless explicitly permitted partial; its report is still emitted. Binary failures produce a diagnostic receipt and no output file. Output files must be new; nothing is overwritten.

Release pipelines can add `"vendor_exports": { ...vendor configuration... }`. Missing/null leaves earlier behavior unchanged. An enabled vendor step reports per-variant routing, and any unresolved demand or source error fails the pipeline. No partial pipeline uploads are allowed. All gates must pass before ordinary BOMs and vendor `uploads/` files are published. Job sets generated by the existing tool use the same pipeline and runner. All-excluded variants retain audit-only files and do not fail for zero purchasing demand. Sample configuration is in `examples/vendor_splitting/pipeline-vendors.json`.

## Source references and acceptance limits

Profile references checked 10 September 2026:
- DigiKey myLists / BOM help: https://www.digikey.com/en/help-support/place-an-order/build-a-bom
- DigiKey myLists: https://www.digikey.com/en/mylists
- Mouser official FORTE upload demonstration: https://www.youtube.com/watch?v=xwwTFMKBxjg
- Mouser-authored demonstration transcript: https://www.linkedin.com/posts/mouser-electronics_how-to-create-a-bill-of-materials-using-the-activity-7092237130877288448-Sf0L
- Mouser BOM: https://www.mouser.com/bom/

Local output parsing, quantity reconciliation, UI downloads, pipeline failure behavior and integrity are tested. Actual supplier-site uploads and actual KiCad/Windows/macOS/embedded-window/IPC host operation remain unexecuted. Read TEST_REPORT.md for exact results. No API credentials, live prices, cloud scraping, telemetry or buying action was added.
