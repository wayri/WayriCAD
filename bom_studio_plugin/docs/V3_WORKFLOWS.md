# WayriCAD BOM Studio 0.3 — Editable BOM, grouping, intelligence and health

Developer preview, 9 September 2026. These are implemented local workflows. They do not establish Xpedition parity, physical component qualification, distributor approval, or KiCad 11 compatibility.

## 1. Edit the BOM itself

In **BOM workspace**, enable **In-grid editing**. Double-click a Value, Footprint, MPN or custom-property cell. You can also focus a cell and press Enter/F2. Type a literal or supported `${VARIABLE}` expression; Enter/Tab queues it, Escape cancels that cell. Edited cells are highlighted. Navigation/redrawing preserves queued drafts. Group membership is based on committed workspace values until edits are staged.

**Review grid edits** shows before/after values, references, active/inherited variants and repeated-sheet effects. Type `EDIT` to stage the complete reviewed transaction; raw-expression replacement also requires the loss acknowledgement. One Undo reverses the transaction. Pending grid drafts are not used by exports, reports or Save workspace until staged. Save workspace asks you to review pending drafts first; stage them and then save again. Changing variant/project warns before discarding drafts. Drafts exist only in the running browser session.

**Paste table…** accepts CSV or spreadsheet TSV with a `Reference` header and real field headings. Example:

```text
Reference	Value	Footprint	MPN
R1	10k	Resistor_SMD:R_0603_1608Metric	EXACT-ORDERABLE-MPN
R2	10000Ohm	Resistor_SMD:R_0603_1608Metric	EXACT-ORDERABLE-MPN
```

Use exact annotated references, or an explicit comma-separated reference list within a quoted CSV cell. Compressed ranges such as `R1-R8` are not inferred. Paste changes properties of existing physical components; it does not create/delete symbols. A bad/unmatched row blocks staging rather than partially applying the table. Paste and modal Edit field use the same review transaction. The earlier general CSV import remains available separately.

Reference, Qty, computed costs/quantities, source path, sheet identity and UUID are not free-editable component fields. Use KiCad to annotate, change the circuit or place/remove components. Editing an MPN or Value does not replace the schematic library symbol, reconnect pins, change pad geometry or certify the substitute.

### Actual KiCad changes are still separate

`EDIT` changes the workspace, not `.kicad_sch`, `.kicad_pro`, a footprint library or a PCB. Save workspace retains it in `.wayricad-bom.json`. For supported native field changes: **Review & native sync → review diff → close KiCad editors → type APPLY**. Native originals are backed up; the adapter reloads the result. Reopen in KiCad, inspect, and use **Update PCB from Schematic** for applicable PCB field propagation. The plugin does not manipulate unsaved editor memory.

Default/base edits to a symbol in a repeated child sheet affect all its physical instances. They can also affect variants that inherit the field. Named-variant overrides are instance-specific. The preview exposes these effects; conflicting values for the same shared base symbol are rejected. Supported aliases are mapped back to actual field names. Generated exact-variable fields remain protected: edit their underlying project variable instead. Existing raw-expression/field-enforcement rules from v0.2 are retained.

## 2. Group by any fields

Open **Group by** and choose Value, Footprint, MPN, Manufacturer, supplier, a custom field, or a combination (up to 30). Quick presets provide Value + Footprint, MPN + Manufacturer, and Ungroup. Raw-expression grouping is available independently of resolved-value grouping.

Groups can be expanded to individual members. Different non-group fields show `<mixed>` instead of silently adopting one member's data. **Edit group…** or double-clicking a group cell edits the group's current filtered members, with full review. Search and population filters run before grouping. A group split/merge caused by your edit occurs after staging. Group pages show up to 50 groups; the complete member set, not just one child, is the target.

Grouping settings persist in the project sidecar. They are independent of column visibility, export templates and property-name enforcement. **Viewing together is not approval to purchase together.** Export grouping still separates incompatible identities, values, footprints, population and sourcing terms—even when the workspace hides those columns. No procurement protection is weakened by using the new view.

## 3. Smart analyzer and consolidation assessment

**Smart analyzer → Run smart analyzer** is an explainable local rules engine. It needs no LLM, model download, API subscription or keys. It analyzes the active variant's fitted, BOM-included population.

It recognizes supported passive R/C/L value notation, such as `4k7` and `4700`, or `100n` and `0.1uF`. SI prefixes retain case: `1m` and `1M` do not mean the same thing. Classification uses conventional reference prefixes and is a heuristic, not a general electrical-unit interpreter. Unsupported labels remain raw; IC MPN suffixes are never decoded as electrical values.

Three report sections are independent:

- **Equivalent labels:** numerically equivalent passive-value spellings. Review label edit opens the ordinary reviewed editor; expressions are not baked automatically.
- **Consolidation candidates:** same normalized nominal value and exact selected footprint, but different manufacturer/MPN identities. Recorded differences in tolerance, voltage, power, dielectric, temperature coefficient/range, technology, current or qualification block a positive candidate assessment. Missing constraints are listed. Even an unblocked candidate still needs engineering qualification.
- **Exact identity aggregation:** fitted demand for the same manufacturer plus exact MPN across references. This aggregates requirements, not source observations or physical compatibility.

Candidate count or potential line reduction is not a savings estimate. The upper bound is not globally deduplicated across all contexts. There are no automatic nearest-E-series substitutions, guessed manufacturer aliases, suffix stripping, BOM rewrites or part approvals. Inspect/edit members is an intentional human edit, not the resolution of all listed risks.

## 4. BOM health: evidence instead of a green score

**BOM health → Health settings** configures footprint roots, optional saved PCB path, stock freshness and market. Defaults are **24 hours** and **IN**. Run BOM health after edits/imports. Reports include workspace revision/variant and display a stale warning after workspace changes; rerun after external file or supplier changes as well. The report is a point-in-time snapshot.

### Selected footprint and symbol inspection

The checker reads the project's `fp-lib-table`, configured footprint directories, supported footprint-directory environment variables and common install locations. It reads local `.kicad_mod` geometry and optionally a saved `.kicad_pcb`. No full-disk scan, library rewrite or remote library download is performed. Unresolved custom environment variables or unusual library layouts may require an explicit directory setting.

Actual numbered electrical pads are counted **uniquely**. Repeated pad numbers such as thermal-via replicas do not inflate the count. Blank paste apertures and non-plated mechanical holes are excluded. Read pad types distinguish SMD/THT/mixed mounting. The report retains positions, sizes, selected source and file hash. Collinear spacings are observations; they are not automatically declared package pitch.

Embedded symbol pin numbers are compared with the selected footprint's pad-number set. Missing symbol pads are errors; extra numbered pads, e.g. possible exposed pads, require review. Inherited symbol definitions or unresolved pin styles produce Unknown instead of an invented pin map. When an unambiguous saved-board reference/path is available, mismatched footprint assignment or board/library pad sets are reported. Board geometry is only a fallback if the reference, name and available schematic path match. This is read-only inspection, not a complete netlist, active-variant or PCB/ERC validation.

### Exact-part package evidence

Import or enter exact manufacturer/MPN facts from a relevant datasheet or product record: package, mounting, expected pin numbers/count, optional pin-function names, pitch, body dimensions, exposed pad, nominal value and ratings. Manufacturer case/whitespace is normalized; manufacturer corporate aliases are not guessed. The MPN is exact after outer whitespace trimming: case, punctuation and full ordering suffix are retained.

The checker can flag mounting mismatch, different expected pad-number sets, pin-count discrepancies, missing/conflicting symbol functions, nominal-value mismatch, rating metadata discrepancies and conflicting package observations. Package family, body dimensions, exposed-pad indications and pitch parsed **from footprint names are explicitly heuristic**, not measurements of the complete land pattern. SOT-23 is treated as a family name, not 23 pins. Manufacturer packages with different naming conventions require human review.

**Equal pin counts do not certify fit.** This build does not fully compare every pad dimension/shape/rotation, mask and paste opening, courtyard, manufacturer recommended land pattern or allowable tolerances. It does not prove thermal/voltage derating, pin-function equivalence, radiation qualification or electrical suitability. Editing Value alone can leave the wrong MPN selected; exact-part evidence can expose that conflict, not autonomously design its correction.

Missing local geometry, exact-part evidence or pin context remains Unknown. A screened-only result is not a qualification. No health score converts lack of evidence into a pass. Existing BOM data/export checks and **BOM health are separate**: a checked export does not mean the health findings are cleared. The advisory report does not introduce an automatic health-based release block in this version.

## 5. DigiKey and Mouser without money or API keys

This build makes **no automatic distributor requests**. It offers a website round-trip and an optional user-initiated capture extension. No account or credentials are entered into WayriCAD. Supplier websites may require free registration to use their complete BOM services. Their current offerings are documented in `RESEARCH_SOURCES.md`; an API being free is different from not needing authentication.

### Whole-BOM website workflow

1. In **Supplier evidence**, export **DigiKey CSV** or **Mouser CSV** for the active variant. The file aggregates fitted exact-MPN demand including board count/attrition; DNP/DNI and BOM-excluded parts do not consume it. The plugin does not upload anything. Review confidential design data before sending it to a supplier.
2. Open **DigiKey myLists** or **Mouser FORTE** using the provided link. Upload/map the request on that website. Check every selected match: a suggestion, partial number or alternate must not be treated as your exact MPN. Review build quantities before accepting the supplier's output.
3. Export/download the website's result where available. Import its **CSV/TSV or values-only XLSX** into WayriCAD. Select worksheet/header row when needed; the mapping preview lets you choose manufacturer, manufacturer MPN, distributor SKU, numeric stock, source, market, observation time, MOQ/multiple and package fields. Regional headers may require manual mapping. An arbitrary historical supplier file is not guaranteed to import without adjustment.
4. Review the records, tick the acknowledgement and type `IMPORT`. Run BOM health. Imported evidence stays in its own ledger: no automatic replacement of component fields, alternates, price assumptions or purchasing approvals.

The importer rejects ambiguous quantities such as a bare “In Stock”, `>100` or locale-dependent decimals instead of treating them as exact stock. Unknown quantities stay blank/Unknown. Numeric English thousands separators are supported. Date/time uses ISO format; supply an offset, preferably UTC `Z`. A date-only/naive time is interpreted as UTC and does not magically become the download time. Leave the date blank when the source observation time is unknown. Fallback values apply only where the source cell is blank.

XLSX import reads values, shared/inline strings and worksheet/header selection, not macros or formulas. Formula cells are rejected; save a values-only copy or use CSV. Legacy `.xls`, arbitrary report layouts, images, PDF extraction and every distributor export variant are not supported. File limit is 10 MiB; parsed XLSX content has separate bounded limits. These are safety limits, not a throughput benchmark.

### Optional product-page capture

The distribution's `browser_capture_extension/` is a separate unsigned **Chrome/Edge Manifest V3** extension. Open the browser Extensions page, enable Developer mode, choose Load unpacked and select that folder. It is not installed by the KiCad installer or published to the extension store.

Open one DigiKey/Mouser product-detail page, click the extension and **Read this product page**. It examines Product structured data and visible two-column attribute rows in that authorized tab, offers an editable review and saves a WayriCAD evidence JSON. Import/review that file in the plugin. The importer also accepts manually authored records; unknowns need not be filled.

The extension requests only `activeTab` and `scripting`. No persistent host permission, cookies, account extraction, hidden APIs, automatic navigation, crawler, proxy, CAPTCHA bypass or order submission. It refuses non-distributor/lookalike domains and non-product routes. Website markup varies; a field or stock count may not be detected. The parser has been tested against controlled HTML fixtures, **not production distributor pages or a real installed extension host**. Manual entry and table import are the supported fallback; no unattended live-stock promise is made. Respect the websites' applicable terms.

### Stock meaning and freshness

Demand is aggregated once for each exact manufacturer/MPN across the active variant's fitted references; variant builds are not silently added together. The most recent observation is considered per supplier, SKU and market. Stock must be numeric, reviewed, sourced, dated, not in the future, fresh enough, and for the configured market to be eligible. Missing manufacturer or a differing ordering suffix does not match.

**Observed covered:** at least one eligible observed offer covers the required quantity after its MOQ/order multiple. **Observed shortage:** eligible observations exist but none individually covers it. **Unknown:** there is no eligible recent numeric observation. The checker does not add stock across distributor SKUs/suppliers, avoiding double-counting the same inventory. A shortage is not proof of a global stockout; splitting orders is not optimized here. Stock is not reserved, independently authenticated or guaranteed purchasable. Review lead time, restrictions, packaging, currency and actual cart availability before purchasing.

Price and stock metadata imported into the evidence ledger do not overwrite the costing assumptions in Sourcing & alternates. Lifecycle warnings use recorded labels/dates and are not a live manufacturer PCN service. The older basic stock fields/data checks still exist separately; use the timestamped health report for this new assessment.

## 6. Reports, privacy and recovery

Health and analyzer views export fresh JSON reports through their Export button. Findings include reason/severity/reference and evidence IDs; part inspection retains local geometry source/hashes. Reports and the evidence ledger may contain proprietary MPNs, references, source paths, URL queries and purchase information. Review before sharing. Template-only bundles remain separate and do not implicitly include these data.

Save workspace retains staged edits, grouping, evidence and health settings; Undo can restore removed evidence in the current session. Imported record IDs and file hashes are consistency aids, not signatures or proof a supplier authored the data. Do not edit the sidecar by hand; malformed evidence/grouping/settings are rejected. Upgrading accepts v0.1/v0.2 sidecars with new defaults. Keep a backup and do not downgrade an updated sidecar into an older release.

The runtime is Python 3.10+ and a browser, with no third-party Python runtime packages. Windows/macOS installation, native KiCad-host launch/reload, current live distributor extraction and KiCad 11 remain target-system acceptance tasks. Read `TEST_REPORT.md` before using native APPLY on working designs.
