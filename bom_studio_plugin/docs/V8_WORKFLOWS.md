# WayriCAD BOM Studio 0.8 — completed integration and direct library creation

This developer-preview package replaces 0.7.1 completely. The two prior partial-source updates are incorporated; do not copy their modules over this installation. Current execution boundaries are in TEST_REPORT.md.

## 1. Project fields before aliases

The actual property name is an identity, the BOM heading is a display label, and a purchasing alias is a separate lookup. The engine exposes exact physical keys as `@field:Name`. This ensures a custom `Qty`, `Source`, `Assembly` or `Currency` does not disappear behind a calculated/application column. An intentional empty string remains empty on the exact-property route. Alias conflicts retain both original observations and produce an error; they are not silently reconciled.

On first open, the view adopts supported saved KiCad order, visibility and labels, appending newly discovered names. Without a saved native setting it uses discovered project properties. Existing saved WayriCAD layouts remain intentional; a legacy-layout banner offers Use actual project fields. The Project fields dialog shows source names, labels, visible selection, order, grouping, presence and blank counts. Its Saved layouts action retains the previous share/import workflow. View changes never run Enforce or delete fields.

Inline double-click/F2 editing, paste, grouping, arbitrary fields, reviewed EDIT and single-session Undo remain. Reference annotation and identity are not freely editable. Exact-property edits preserve generated-field and variable-loss checks. Exclusion attributes are explicitly inverted into the native boolean, not confused with inclusion flags. Repeated-sheet and inheriting-variant effects appear in the review. Save workspace and native APPLY stay separate.

Raw expressions can be viewed independently of resolved text. Sheet scope and descendant inclusion narrow the view; Reset view filters clears the extra numeric/drill-down scope too. The complete field audit is downloadable. A view is capped at 200 columns with disclosure; this is not a truncation of stored component metadata.

Native preset adoption copies the view only. Importing a native export preset warns about semantics not representable in WayriCAD. For exact native output, use the next section rather than treating WayriCAD procurement grouping as identical to KiCad's grouping.

## 2. Native KiCad BOM export path

Native KiCad BOM delegates to the installed `kicad-cli sch export bom`. It detects version/help and accepts only advertised requested options. It preserves native bytes instead of passing them through WayriCAD filters, purchasing grouping or CSV formula protection. Treat exported formulas/untrusted text accordingly.

It requires explicit acknowledgement that **saved native files only** are used. Pending workspace/grid edits, unsaved KiCad memory and BOM-only variants are not included; no implicit native synchronization is performed. Native sources are hash-checked before/after. A missing executable is reported, not substituted with another engine. In this environment the unavailable path and an injected CLI contract were tested; actual CLI execution was unavailable.

This does not claim every native in-memory editing feature, arbitrary expression/context or future file format is reimplemented. Existing unsupported-source/native-write gates remain. The capability path separates native fidelity from added WayriCAD features.

## 3. Parts-finder browsing and categorization

Local catalogue now has category navigation, search results, manufacturer/preference/lifecycle-evidence/asset filters, sorting, paging and a detail panel. Selection displays exact part metadata, classification reasons, recorded health and source-backed symbol/footprint mini previews. Full preview opens the existing symbol/footprint/3D inspector, source-set selection, transformations, originals and provenance. Up to four parts can be compared; differing supplied strings are highlighted without implying interchangeability.

Explicit Category/ComponentType wins. Otherwise description/keyword fields and reference prefixes such as R, C, L, D, Q, U and J suggest a family. U alone stays broad; suitable descriptions can narrow regulators/MCUs/amplifiers. Conflicting hints retain warnings. Classification is read-only metadata guidance, never a physical field rewrite, preferred status, stock guarantee or qualification.

A derived SQLite index holds revision-aware lightweight summaries. The index never changes curated revisions, evidence or authoritative epoch. Full records are loaded for the requested page; category facets describe the full library, not the current filtered intersection. Numeric/asset filters apply before pagination; typed predicates may scan all text-matched lightweight records. Library changes invalidate preview/comparison context to prevent stale geometry from a different catalogue sharing a part ID/revision.

The stock/lifecycle feed has not become live. All health remains based on existing entered/imported dated evidence. See the v0.3/v0.6 guides for the no-key supplier workflow and unknown/freshness semantics.

## 4. Create native libraries directly — no source library required

The creator is available from the welcome page and Library & control. Harvest projects without an attached catalogue opens this creator rather than failing with a missing-library message.

| Mode | Input | Output |
|---|---|---|
| Empty | New directory and nickname | Valid empty `.kicad_sym`, `.pretty`, `.3dshapes` plus an empty local catalogue |
| Projects | Explicit saved projects/directories | New populated catalogue plus captured native symbols, footprints and model originals |
| Catalogue | Existing catalogue and explicit selected IDs/all-parts choice | Native snapshot without mutating the source catalogue |

No catalogue/library is needed in Empty or Projects mode. Source paths are explicit; no whole-disk or online scraping occurs. Custom library/model roots and variable aliases use the existing asset-resolution JSON. Project mode can include subdirectories and all variants. Partial project failures require explicit acknowledgement, separately from the strict assigned-asset policy.

### Preview, CREATE, attach

Enter an absolute new destination with an existing parent. The nickname is a portable name, letter first with letters/digits/underscore/hyphen. The preview assembles privately, reports progress, and can be canceled. It does not create the destination or modify source projects/catalogue. Review counts, missing assets, asset-set choices, source revisions and native-byte hashes; the whole plan can be saved.

Type CREATE. Apply re-reads/reassembles inputs and rejects stale source/catalogue revisions/native hashes, then exclusively creates the new folder. Ordinary copy errors roll it back; existing destinations remain untouched. All output files have a manifest and are checked after copying. Random new catalogue IDs/audit timestamps are created on apply; the review binds sources and native geometry rather than pretending those metadata bytes are identical to preview. Power-loss atomicity is not claimed. Filesystem owners are trusted; this is not a hostile-OS sandbox.

Attach resulting catalogue is optional and checked by default; remember-on-this-computer is a separate explicit choice. Project attachment must be saved with the workspace to persist. Catalogue writes themselves are immediate. New catalogue context clears old preview/comparison choices.

### Asset and registration semantics

Captured symbols are independent supported definitions, not inferred substitutes. Footprints are captured/normalized supported native definitions. Every stored original model is copied byte-identically with its existing transform/visibility; symbol-to-footprint links use the chosen nickname. Source models can be internal/embedded or external local files under existing resolver rules. Missing assigned originals, external auxiliaries and unsupported back-side normalization remain findings, not fabricated models. Strict export can refuse them. An unassigned optional 3D model is different from a missing assigned one.

The creator writes native files directly. **It does not edit existing global/project library tables.** Add its symbol and footprint paths through KiCad Preferences using the same nickname. `table-snippets` contains entries to merge or inspect, not whole tables to overwrite yours. Models use the chosen absolute destination; relocate by explicit relinking/recreation. Further catalogue changes do not auto-overwrite this snapshot. Publish the next revision into a new folder.

This is library creation/harvesting, not a visual symbol/footprint drawing editor. Empty mode intentionally has no invented parts. Add/edit geometry in KiCad's editors or harvest it from genuine projects. Back up the entire newly created folder/catalogue while closed. Review redistribution rights.

## 5. Embedded desktop and live mapping

The normal action uses a modeless plugin-owned desktop window with the local UI embedded. It is not docked inside KiCad's wxWidgets process. Browser launch requires explicit `--ui browser`. Missing webview/runtime is an error with interpreter/dependency guidance. Native downloads use an authenticated Save dialog, not a general filesystem/eval bridge. Arbitrary file URLs are blocked; external HTTP links are explicit. Quit/close stops the associated local server; the close confirmation warns about unsaved workspace/grid/forms.

The selection adapter prefers the official underlying protobuf UUID path and supports documented wrapper forms. It never overrides a conflicting UUID with an equal reference. Mapping diagnostics list rejected paths/reasons. Repeated failures appear once inline, not as an endless toast stack. Optional partial group linking selects only known members and reports skipped ones. It cannot select an unmatched single part. Existing selection stays unchanged when a strict request cannot be matched.

KiCad 10 schematic relay still depends on native PCB↔schematic cross-selection. Real SDK transport, editor focus, your project mapping and native window hosting were not executed here. Selection and bulk-edit checkboxes remain separate. The bridge does not synchronize pending BOM edits into editor memory.

## 6. CLI

There are 36 top-level command families, preserving the earlier 33. Added: `fields`, `native-bom`, `library-create`. The finder adds category/manufacturer/lifecycle/sort/summary options. A new library can be created entirely headlessly with the same preview/apply engine. See CLI_REFERENCE.md and `examples/library_creation/`.

Optional GUI code is imported only for GUI/diagnostics paths. Existing CLI outputs, pipeline gates, signed-local review boundaries, job-set generator and native APPLY policies remain. No automatic library mutation or native write is inserted into manufacturing pipelines.

## 7. Sources and acceptance

Primary interfaces used: KiCad addon packaging https://dev-docs.kicad.org/en/addons/ ; native CLI https://docs.kicad.org/10.0/en/cli/cli.html ; native library tables https://docs.kicad.org/10.0/en/eeschema/eeschema.html ; IPC plugins https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/ ; pywebview engines https://pywebview.flowrl.com/guide/installation.html and version https://pypi.org/project/pywebview/6.2.1/ . Accessed 10 September 2026.

Read TEST_REPORT.md for actual execution. Synthetic parser/contract/browser tests do not establish KiCad-host conformance, Windows/macOS acceptance, full accessibility, live supplier truth or electrical/mechanical qualification.

### Native CLI capability details

The probe uses `kicad-cli version` and the installed `sch export bom --help`. Empty/default variant arguments and disabled switches do not require an advertised flag. KiCad 10 documents `--include-excluded-from-bom` as deprecated with no effect; it must not be relied on to force population. The native passthrough preserves KiCad's output rather than substituting WayriCAD's interpretation.
