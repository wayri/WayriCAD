# Shared parts, native libraries and alternates

Open **BOM workspace → Shared parts library**. Everything runs locally.

## Save and reuse across projects

1. Choose an existing catalogue, or enter a new absolute folder and choose **Create this library**. Keep it outside the plugin installation. The selected folder is remembered across projects.
2. Save your workspace, then **Review project parts + assets**. The scan uses the originating project and saved workspace, including variants. Review the captured symbols, footprints, models and unresolved references; type IMPORT to merge observations.
3. Exact manufacturer/MPN identities merge. Identical asset bytes share a SHA-256 identity. Missing manufacturer/MPN records remain source-scoped generic records, preventing unsafe cross-project pooling. Changed metadata and asset assemblies retain provenance/conflicts; they are never silently overwritten.
4. **Save templates** stores a reusable bundle in the same catalogue. In another project, choose **Load saved templates**. Conflicting template names are retained with imported names. Component rows and project variable definitions are not template payloads.

## Register assets globally in KiCad

Choose the correct KiCad version configuration folder and a library nickname, then **Review global registration**. Resolve missing assets, critical field conflicts and ambiguous source sets in Library & control first. The backend accepts an explicit part-ID to asset-set-ID choices mapping for ambiguous assemblies; the simple dialog deliberately blocks these until resolved.

Close KiCad library managers, review both proposed table entries and type REGISTER. Reopen editors after registration. Only the chosen nickname is added/updated in `sym-lib-table` and `fp-lib-table`; unrelated entries and comments are preserved. An existing nickname pointing elsewhere is refused. Original tables receive uniquely named backups. Failed second-table writes roll back the first table, unless another application has already changed it.

Native snapshots are stored under `catalogue/native/<revision>/`. Symbols and footprints have readable manufacturer/MPN names with a stable identity suffix. Shared model blobs use hash filenames under `.3dshapes`; footprint links retain their transforms and point to that snapshot. Previous snapshots remain as rollback history, not extra registered parts. Moving the catalogue later requires republishing/relinking. Stored assets retain their original licenses.

KiCad symbols, footprints and models remain separate native assets; the catalogue links them and holds project usage, notes and templates. No missing geometry is invented. Registration uses local advisory locks, stale-table checks and atomic per-file replacement. It cannot prevent an unrelated KiCad process from writing a table concurrently; keep library managers closed during publication.

## Plugin-only Alt selectors

Every visible component has an **Alt (plugin only)** selector. In grouped views, choose the individual reference from the group's selector; expanded rows have individual controls. Search the shared catalogue with keywords such as `IC STM32`, `resistor`, or `capacitor X7R`.

Optional bounded regex supports literals, anchors, character classes, `|` and one quantifier per alternative, for example `STM32.*`. Groups, backreferences, braces and repeated quantifiers are rejected. Searches inspect at most 5,000 catalogue records and explicitly report truncation; use Library & control's indexed finder for larger catalogues.

Suggestions rank literal value/package/specification matches. Each candidate shows differing and unknown fields. Pinout, electrical function and interchangeability are **not verified**. Record a candidate and an engineering note, then save the workspace. This does not replace native components or change purchasing exports. Selections are per instance and variant, retain the catalogue revision and support undo/clear.

## Manufacturing handoffs

The assembly-export screen retains CSV/XLSX and audited ZIP bundles for JLCPCB, PCBWay, HQPCB, NextPCB, Sierra Circuits, PCB Power and Seeed, plus generic mappings. AISLER, PC Process and Krypton Solutions have separate editable mappings requiring explicit review. They are not claimed as portal-certified templates. Obtain the current recipient workbook and adjust column mappings before ordering.

AISLER documents CSV/XLSX input for [Simple Supply](https://aisler.net/en-US/products/supply); assembly workflows can instead derive part data from design files. [Krypton documents assembly services](https://www.krypton-solutions.com/our-services/assembly/), but its current BOM workbook is unverified. PC Process's official current import schema is also unverified. The profile warnings retain these limits.

Normal Exports & templates continues to support grouped/individual BOMs, DNP/test-point exclusions and separate lists. Assembler handoffs preserve their per-board quantity contract; they do not silently apply purchasing batch quantities.
