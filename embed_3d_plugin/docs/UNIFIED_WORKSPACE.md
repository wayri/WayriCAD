# WayriCAD Embed3D 0.4.1 — unified component workspace

**0.4.1 fixes the component-table lifetime/blank-scan defect in 0.4.0.** See `SCAN_HOTFIX.md`.

This guide describes the **new default** window. The old model-only dialog is now an advanced tool under Options, not the main path for symbols/footprints/3D embedding. This release has automated coverage but has not run in a real KiCad/wx session here.

## 1. Sources: what you are selecting

Save the PCB, schematic and all edited child sheets in KiCad 10 first. Open WayriCAD Embed3D from the PCB Editor. The saved active board and same-stem schematic are detected when present. Choose a different root schematic explicitly where filenames differ. Clear a source field to work on only the PCB or only the schematic.

The component list is assembled from the saved native files. PCB footprints and schematic symbols match using their native UUID path where possible. A unique reference is only a fallback when a board footprint has no usable path; conflicting UUIDs do not get silently rematched by reference. A component with several symbol units in one sheet has one Symbol checkbox controlling those units. Unmatched/ambiguous components remain separate rows.

A symbol's native cache already lives in the schematic. The checkbox means “include this component in the chosen reusable-library/archive operation,” not “delete/restore its native cache.” A footprint's native geometry likewise remains on the PCB regardless of archive selection.

The same child sheet file can be instantiated several times. Operations act on saved files, so one file's checked symbols affect all instances of that file. The window warns about this. Independent top-level sheets are not discovered from flat/multi-root project settings; process them deliberately.

## 2. Global and component checkboxes

The visible matrix has Component, Value, Symbol, Footprint, 3D models and Status columns. Each available asset has its own real native toggle cell. An unavailable asset has no checkbox. Model status is informational: “External” means a resolved file, “Embedded” means a payload entry is present, and “Needs attention” or “Missing payload” requires review. Full payload validation occurs during operation planning, not just a superficial status label.

Global Symbols, Footprints, 3D models and All types controls use unchecked/mixed/checked states. They affect all components, not only search-visible rows. Per-component edits update the global state. Filtering and sorting do not lose checked items. The footer and counts explicitly state this scope.

A 3D checkbox controls all model entries attached to that component. This is not a per-model matrix; for individual linked model entries use the existing advanced model tools. The original model format and scale/rotation/offsets/hide/opacity remain unchanged.

To select only one type, clear All types, then check that global type. To select an individual component, clear All types and check the desired cells. There is no extra hidden type mask that can override a checked cell.

## 3. Choose one of the five actions

| Action | Selection | Asset writes | Design writes |
|---|---|---|---|
| Embed checked | Exact checked type/component pairs | Local working libraries may be generated in the new design | New copy only |
| Embed all | Every available asset, explicitly overriding checkboxes | Same as embedding | New copy only |
| Unbundle | Exact checked type/component pairs | Extracted files and hash manifests | None |
| Relink | Exact checked type/component pairs | May create a project-specific footprint library view in the extraction folder | New copy only |
| Unbundle & relink | Exact checked type/component pairs | Extraction and library view in one coordinated operation | One new PCB/schematic copy |

Each button builds an **in-window preview**. Review it and press Apply preview. No writes occur just from selecting a checkbox, scanning or preparing an action. Change any input/option/checkbox and the preview is invalidated. The output cannot silently use a different selection than the one reviewed.

Embed all does not silently toggle the displayed cells. Its preview says that it overrides the matrix and includes all available assets. Subsequent other actions still use the displayed selection.

## 4. Destination fields

The Asset folder is the reusable-file destination for extraction and the source for Relink. The New design folder must not exist. Embed and Relink create a copy there with original-source snapshots under `WayriCAD Embed3D-originals/` and an operation report. Existing source files and live editor buffers are never overwritten by the main workspace.

Choose sibling folders for combined unbundling/relinking. For example:

```text
project/
    source-board.kicad_pcb
    source-board.kicad_sch
    assets/
        WayriCAD Embed3D-workspace.json
        pcb/
            WayriCAD Embed3D-extraction.json
            WayriCAD_Embed3D_Footprints.pretty/
            models/
            linked/<output-specific-key>/...
        symbols/
            WayriCAD Embed3D-extraction.json
            WayriCAD_Embed3D_Symbols.kicad_sym
            archives/...
    external-copy/
        source-board.kicad_pcb
        source-board.kicad_sch
        fp-lib-table
        sym-lib-table
        WayriCAD Embed3D-originals/...
        WayriCAD Embed3D-operation.json
```

Only selected types create their corresponding outputs. External symbols use the extracted `.kicad_sym`. The board's working footprint view points to the extracted models with the chosen project-relative or absolute paths. A project-specific view avoids altering a previously relinked project's model paths when the same assets are reused.

Relink reads the root workspace manifest and the per-domain extraction manifests. A previous 0.3 single-domain extraction can also be selected directly. An arbitrary folder of loose models/libraries without a verified mapping is not treated as an extraction. Keep the manifest and its files together. Edits after extraction require a new reviewed operation.

Relative paths use `${KIPRJMOD}` and can contain `../`. Move the new design and extraction folder together with the same relative layout. Relative Windows cross-drive paths are impossible; use Absolute paths for that storage arrangement. This workflow does not silently copy external assets into a supposedly standalone output and then delete them.

## 5. Embedding and library lookup

When a 3D checkbox is selected for Embed, the original linked file bytes are embedded in the PCB pool and referenced by the native embedded URI. Standard and user-supplied file paths use the same resolver. Missing selected models stop the operation with a path-specific reason. A missing unselected model does not block an unrelated symbol-only operation.

When a Footprint checkbox is selected, native KiCad normalization supplies the standalone definition. This is necessary for board-side/orientation and library coordinates; no hand-written pad-coordinate transform replaces KiCad. The definition is stored as an actual `.kicad_mod` payload and recorded in `WayriCAD_Embed3D_components.json` in the PCB. With local relinking enabled, an editable `.pretty` library is also written in the new design and the checked board instance is linked to it.

Selecting a footprint alone does **not** newly embed unchecked external models. Already-embedded model resources needed by a standalone footprint are preserved/hydrated so its definition is not broken. Uncopied external references are rebased where resolvable; unresolved and indirect resources remain external dependencies.

When a Symbol checkbox is selected, its as-drawn native cached definition is exported into a reusable library attachment in the schematic. Optional local relinking creates a real `.kicad_sym` and project `sym-lib-table` entry. If checked and unchecked instances share an old cache entry, only selected instances are relinked and a needed original cache entry is retained for unchecked ones. Pin UUIDs, unit choices, fields, wiring and other instance data remain unchanged.

KiCad native library lookup requires real filesystem libraries; attaching a file is not a new library backend. The implementation never puts an embedded file URI into a library-table field as though it were a mounted `.pretty` directory. Embedding means actual recoverable archive bytes inside the design plus optional native-compatible working libraries.

Library nickname conflicts are handled by allocating a suffix such as `_2`, not by repointing an unrelated library. Old entries are retained. Symbol library relinking and schematic Footprint fields are separate: the latter are not automatically synchronized with changed PCB footprint IDs. Review assignments before Update PCB from Schematic to prevent restoration of old footprint links.

## 6. Unbundling and removal

Unbundle makes real files and never relinks the source. It supports each of the three types separately or any combination. Native normalized footprint extraction captures current as-placed edits. Previously embedded archive mode recovers archived definitions; an archive may be older than later geometry edits, so use As placed for the latest state.

By default only already-embedded models are extracted. Enable Also unbundle external models to collect resolved external model bytes too. Exported footprints retain their needed existing embedded data when model extraction is unchecked. External models are not converted. Known secondary WRL/texture/Inline dependencies are rejected rather than labeled fully portable.

Remove redundant attachments after relink is OFF by default. It acts only on the new copy. Selective pruning retains footprint archives for unchecked components and model data still referenced by unchecked instances or retained archives. Symbol archive removal is conservative when the library contains unchecked components. Native `lib_symbols` caches and placed PCB geometry are never removed. Unrelated attachments are not treated as plugin-owned data.

## 7. Validation and failure handling

Scan displays the discovered component count. No search matches and no saved components have distinct messages. A failed scan shows its error, locks any old rows, and disables design actions. Use **Options & library tools → Save scan diagnostics…** even without a preview. Diagnostics contain local paths and runtime/count/error information, not file payloads; review before sharing.


Scan/preview records source hashes; Apply rechecks the sources, relevant sidecars and extraction files. Sources modified after the scan or sidecars created after the preview require another scan/preview. Safe output names, symlink checks, collision checks and exclusive file creation are enforced by the file layer.

Combined Unbundle & relink uses an in-memory extraction plan to prepare the relink before any output is published. Apply extracts the reviewed assets, then stages the combined design and runs selected native validation before publishing it. Failure can leave verified asset files or unused library-view files, but the original designs are untouched and the failed final design directory is not published. Operations are not guaranteed atomic during sudden power loss.

Parsing/compression runs in a worker; the UI can request cancellation during this stage. Native footprint normalization, detached parser checks and final publication stay on the GUI thread. Long native operations can temporarily make the UI busy. There is no unsafe wx event pumping during publication.

The Validate with KiCad option is enabled by default. PCB validation uses detached native objects and a load/save check. Schematic validation requires a local KiCad CLI and exports a temporary netlist without invoking a shell. A missing required CLI blocks publication until it is provided or the user explicitly disables that option. This check is not ERC, DRC, rendering, electrical-equivalence proof or native GUI acceptance.

## 8. Advanced tools and remaining limits

The earlier model/footprint-file repair, supplied-library packaging, ordinary library extraction, and legacy live-model tools remain under Options → Standalone library / live-board tools. Their existing additional dialogs are advanced paths; the current three-type primary operation is not hidden there. After any legacy live edit, save and Scan again.

No Schematic Editor toolbar action is installed by the SWIG plugin. The PCB Editor hosts saved-schematic processing. A root in another folder can be processed separately; it is not silently combined with the wrong board project. Save legacy schematic formats in KiCad 10 first. Existing version guards reject unreviewed schematic formats.

The workflow is not a complete collector of arbitrary SPICE models, datasheets, drawings, project resources or independent top-level sheets. Large production-board performance and operating-system-specific GUI behavior require further host testing. See `TEST_REPORT.md` and `ACCEPTANCE.md`.

## Primary references

Reviewed 10 September 2026; documentation review is not native execution:

- KiCad PCM runtime, layout and icon rules: https://dev-docs.kicad.org/en/addons/index.html
- KiCad schematic caching and embedded files: https://docs.kicad.org/10.0/en/eeschema/eeschema.html
- Native schematic format: https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/
- wx data model value, enable and notification contracts: https://docs.wxpython.org/wx.dataview.DataViewModel.html
- wx table model: https://docs.wxpython.org/wx.dataview.DataViewIndexListModel.html
