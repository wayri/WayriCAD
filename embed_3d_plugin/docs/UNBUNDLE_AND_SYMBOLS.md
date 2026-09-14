> **0.4.0 navigation:** the new default is the unified component window documented in `UNIFIED_WORKSPACE.md`. This document retains the earlier backend/advanced workflows; their separate dialogs are under **Options → Standalone library / live-board tools…**. See `TEST_REPORT.md` for current validation.

# WayriCAD Embed3D 0.3.0 — unbundling, relinking and schematic symbols

**Testing release for KiCad 10.0.x.** Native installation, wx layout, native footprint normalization, schematic CLI acceptance and interactive rendering have not been executed in the build environment. The new workflows are saved-file tools, launched from the PCB Editor's WayriCAD Embed3D action. They do not install a Schematic Editor toolbar action or modify an open schematic buffer.

## The two-step contract

**Extract files** writes actual reusable files to the asset folder you select. The source PCB/schematic is read, not rewritten. It does not change library IDs or replace model links in the design.

**Relink extracted files…** is a different button and operation. Select a verified extraction folder, preview the changes, choose a **new design folder**, then choose **Create new design copy**. The new copy uses the extracted files. The original design and its open editor buffers remain unchanged. Extraction never implies consent to relink or to delete embedded payloads.

All new design copies keep the source filenames, source-file snapshots in `WayriCAD Embed3D-originals/`, and a `WayriCAD Embed3D-operation.json` report. Existing output folders are refused for design copies. Extraction can reuse a folder only when existing target files are byte-identical; differing files are not overwritten. This is intentionally not an in-place project migration.

## PCB: footprints and 3D models

Open **WayriCAD Embed3D → Unbundle PCB…**. Choose a saved `.kicad_pcb` and an asset folder; the folder may be new. You can select footprints, 3D models, or both. A separate checkbox optionally copies models that are already external. The default only extracts embedded model data.

For footprint definitions, choose one of two sources:

| Source | Meaning |
|---|---|
| **As placed — native footprint normalization** | KiCad converts each saved board instance to an editable library footprint, including its board-specific geometry. Handles library coordinates and side/orientation through KiCad, rather than custom coordinate math. Works on ordinary boards, not only WayriCAD Embed3D packages. Requires the native GUI bridge. |
| **Archived definitions — packaged PCB only** | Recover the reusable definitions already archived by Package PCB. This can differ from current as-placed geometry when supplied-definition mode was used. Also available to the pure-Python CLI. |

Footprints without any model are included. Different as-placed instances are not collapsed merely because their original Library:Name is the same. Models are exported in their existing formats without conversion or a STEP/WRL substitution. Names include content hashes; identical content with the same sanitized basename reuses one file. Hashes also prevent different same-basename files from colliding.

The output resembles:

```text
chosen-assets/
    WayriCAD Embed3D-extraction.json
    UnbundledFootprints.pretty/
        F00001_R_0402_1005Metric.kicad_mod
    models/
        model__<content-hash>.step
    linked/                       # created only by separate footprint relinking
        <project-specific-key>/
            UnbundledFootprints.pretty/
                F00001_R_0402_1005Metric.kicad_mod
```

The initial `.pretty` files use absolute references into the selected asset folder for directly opening that library. During relinking, a **project-specific library view** is generated in `linked/`. That view uses the chosen project's relative or absolute paths, so relinking a second design does not rewrite the first design's library view. The PCB's project `fp-lib-table` points to this view inside the extracted folder. The models remain in the same extracted `models/` directory; they are not copied back into the new PCB unless you embed them again later.

Choose **Project-relative paths** for portable project/asset trees on one filesystem drive. The paths use `${KIPRJMOD}` and may include `../` when the assets are beside the new design folder. Choose **Absolute paths** for a fixed shared location or Windows cross-drive storage. Relative paths cannot cross Windows drive letters. Move the design and asset directories together without changing their relative relationship; alternatively run Relink again using the moved asset folder. The extraction manifest records the files and their hashes, not a universal filesystem mount.

Relinking offers independent **footprint library IDs** and **3D model paths** checkboxes. When only one category was extracted, the unavailable relink category is disabled. Board pad geometry, net names, placement, rotation, tracks and zones are not replaced from an external library. XYZ model scale, rotation, offsets, hide/opacity settings and other model properties remain attached to each instance and are checked for preservation. The corresponding library footprints also retain their model transforms.

Uncopied external models remain external dependencies. Explicit `${KIPRJMOD}/…` model links are rebased to their original target when copying a PCB to another folder. Other custom-variable and indirect resource dependencies are not a full dependency-graph migration. Review scan warnings and use **Also copy already-external models** when those model files should be included.

### Optional removal of embedded PCB data

**Remove redundant archive/model attachments after relinking** is off by default. It applies only to the new design copy. Extracted model attachments are removed only where native references no longer use them. Models referenced by a retained footprint archive are protected. Removing both footprint and model links can also remove the verified WayriCAD Embed3D footprint snapshots and package manifest. Unrelated attachments are retained.

Removing embedded files does not remove the placed footprint geometry from the PCB. That geometry is part of the native board representation. After removing the package archive, use the extracted library rather than expecting the old Rebuild embedded library action to recover a removed archive.

## Schematic: native caches, library archives and external relinking

Open **WayriCAD Embed3D → Schematic symbols…** and select the saved root `.kicad_sch`. A saved/blank PCB Editor window can host this tool even when the schematic is the only design you are processing.

**Save the schematic and its child sheets in KiCad 10 first.** The symbol tool accepts the reviewed KiCad 10 schematic format range (20251028 through 20260306) and generates symbol libraries using KiCad 10's 20251024 library format. Older files are not silently reinterpreted under a newer library version: flags, empty-text conventions and private-field syntax changed historically. Newer unreviewed format versions are also refused. Open/save or upgrade using KiCad before retrying.

Modern schematics already store the actual used symbol definitions in `lib_symbols`. The plugin never deletes that cache. External library IDs and self-contained cached symbol definitions coexist: relinking does not make the schematic stop carrying its native symbol definitions. An attached `.kicad_sym` is not an automatically mounted symbol-library backend.

### Embed symbol archive…

The existing, as-drawn cached definitions are collected into a reusable `.kicad_sym` payload and embedded as a native file attachment in the root schematic. A mapping manifest is also embedded. This is real library data, not a filesystem pathname.

You may add supplied `.kicad_sym` files. They are archived byte-for-byte, including valid derived-symbol relationships within the supplied library. They are **not** substituted for the pins, symbol shape or fields in the drawing. A missing or unflattened used cache stops the operation with a repair instruction rather than guessing from a global library.

By default, library IDs in the drawing remain unchanged. The optional **Also create a project-local symbol library and relink its IDs** writes an editable library next to the new schematic, adds its project `sym-lib-table` entry, and relinks the instances/cache keys to those as-drawn definitions. The internal archive remains available for extraction later. No unsupported `kicad-embed://…` URI is written as a library-table mount.

### Extract files

This writes a reusable `UnbundledSymbols.kicad_sym` from the actual cached definitions, not whichever version happens to be installed globally. Embedded standalone symbol-library archives are additionally exported under `archives/`. Existing embedded resources actually referenced by a symbol are retained within the exported symbol definition where needed. External datasheets, SPICE files and arbitrary project resources are not newly collected.

Options include a custom library nickname, inclusion of unused cached definitions, and following hierarchical child sheets. Shared child files are read once. Identical effective symbol definitions are reused; same-named definitions with different geometry or properties remain distinct. Multi-unit/body-style names and native `lib_name` overrides for edited cached symbols are handled explicitly.

### Relink extracted files…

The new schematic copy's symbol `lib_id` values and native cache keys are changed together. The project `sym-lib-table` points directly to the extracted `.kicad_sym` file, using the selected path style. Wires, labels, pins, unit selection, instance UUIDs, reference/value fields, footprint-assignment fields and other instance attributes are checked for structural preservation. This is not an Update Symbols from Library operation.

Optional removal deletes only verified, unreferenced WayriCAD Embed3D symbol-library archive attachments. **The native `lib_symbols` cache is always retained**, including when external links are selected. This is the compatible distinction between unbundling a reusable library archive and deleting the schematic's own component definitions.

## Hierarchy and scope

By default the selected root and recursively referenced hierarchical child sheets are processed. Relative child paths and saved project text variables are resolved from the selected design, not another open project. External child sheets are copied into a safe `external-sheets/` directory in the new output and their Sheetfile references are remapped. Cycles, missing sheets, unresolved variables and conflicting resources stop the operation.

**Include hierarchical child sheets** off processes the selected sheet only. A warning records that the output is not a complete hierarchy. Independent top-level sheets in KiCad 10's flat/multi-root project list are not automatically discovered from the project file. Process those deliberately; do not assume that choosing one root archives every independent top-level schematic.

Saved `.kicad_pro`, `.kicad_dru` and local library tables are copied where present. Explicit project-relative library-table URIs are rebased to preserve unrelated library locations. Other relative resources inside project settings (drawing sheets, simulation data, custom-variable paths and similar files) are outside this workflow's complete migration scope. Unsaved project settings are not captured.

**PCB footprint IDs and schematic Footprint fields are not automatically synchronized by symbol relinking.** Symbol `lib_id` and footprint-assignment fields are different data. Review synchronization separately before Update PCB from Schematic; otherwise the schematic's old footprint assignments can restore old board library IDs. Neither the footprint nor symbol workflow silently updates geometry from a library.

## Safety and verification

Extraction plans record source hashes. Relinking verifies the selected source and every extracted file against the manifest. Later edits in the design or extracted assets require a new reviewed extraction; they are not silently treated as equivalent. In the GUI, source/asset inputs are also checked against the preceding relink/embed preview. Model bytes are read back after publication. Safe filenames, file-size budgets, duplicate-name checks, symlink refusal, and exclusive file creation prevent common extraction/overwrite hazards.

Failed extraction removes new files where safe and does not delete pre-existing files. Failed design creation discards the staged new design folder. A PCB's verified project-specific library-view files may remain in the selected asset folder after a later native validation failure; they are harmless, unused outputs, not edits to the original library. Multi-file operations are not guaranteed atomic under sudden power loss. Keep the operation manifest, extracted assets and original-file snapshots until verification is complete.

Native PCB validation uses detached objects and a load/save round trip. Schematic native validation, when enabled, invokes the locally installed KiCad 10 CLI to export a temporary netlist without running a shell. It is a parser/export check, **not** ERC, DRC, electrical-equivalence certification, 3D rendering or interactive GUI acceptance. Schematic validation is selected by default when the CLI can be found; otherwise the UI shows the missing-tool limitation. All format/identity preservation checks still run when optional native validation is disabled.

The pure-Python reader verifies SHA-256-bearing embedded entries and always SHA-256-checks extraction manifests. For legacy/native entries carrying a different checksum representation, the original checksum is preserved rather than claimed as independently verified by a new algorithm. Native KiCad parsing is the additional format/checksum authority when enabled.

## Command-line examples

Run from the complete extracted source distribution with Python 3.10+. No writes occur without `--apply`.

```text
python -m embed_3d_plugin extract-pcb board.kicad_pcb --output assets --models-only
python -m embed_3d_plugin extract-pcb packaged.kicad_pcb --output assets --apply
python -m embed_3d_plugin relink-pcb packaged.kicad_pcb --assets assets --output external-pcb --apply
python -m embed_3d_plugin relink-pcb packaged.kicad_pcb --assets assets --output external-pcb --path-mode absolute --prune --apply

python -m embed_3d_plugin extract-symbols circuit.kicad_sch --output symbols-assets --apply
python -m embed_3d_plugin relink-symbols circuit.kicad_sch --assets symbols-assets --output external-sch --apply
python -m embed_3d_plugin embed-symbols circuit.kicad_sch --output embedded-sch --local-links --apply
python -m embed_3d_plugin embed-symbols circuit.kicad_sch --output embedded-sch --supplied custom.kicad_sym --apply --validate-cli
```

PCB CLI footprint extraction uses the packaged footprint archive. Use the GUI for as-placed extraction of ordinary PCBs. Other options include `--footprints-only`, `--include-external`, `--nickname`, `--sheet-only`, `--include-unused`, `--var NAME=VALUE`, and `--json`. CLI output is not a native KiCad integration-test result unless the explicit schematic CLI validator actually ran.

## Reviewed primary references

Reviewed 9 September 2026; these are API/file-format references, not a claim that the build was run in KiCad.

- KiCad 10 schematic native symbol caching and embedded files: https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- Native schematic format: https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/
- KiCad 10 format version history: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/sch_file_versions.h
- Native `lib_name`, `lib_id`, root embedded pool and schematic serialization: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr.cpp
- Native schematic/parser cache resolution: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_parser.cpp
- Native symbol-library unit naming and embedded resources: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/eeschema/sch_io/kicad_sexpr/sch_io_kicad_sexpr_lib_cache.cpp
- Native footprint library IO/normalization: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp
- CLI schematic netlist command: https://docs.kicad.org/10.0/en/cli/cli.html
- PCM package runtime/layout: https://dev-docs.kicad.org/en/addons/index.html
