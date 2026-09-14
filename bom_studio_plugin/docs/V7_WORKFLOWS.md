# WayriCAD BOM Studio 0.7 — Searchable catalogue with stored design assets

Developer preview • 9 September 2026. This guide takes precedence over the v0.6 statements that models were omitted. The reusable catalogue now stores symbol definitions, footprint definitions and referenced 3D files. It is not a full KiCad renderer or a component qualification certificate.

## 1. Search without opening a project

Start WayriCAD and select **Browse local catalogue** on the welcome page. Attach an existing catalogue or create a new one. An open project is not required for catalogue search, asset inspection, metadata editing, health assessment, project harvesting or native-library export. With a project open, use **Library & control → Catalogue**.

Search covers manufacturer/MPN, internal part number, value, footprint, notes, tags, custom properties and existing indexed provenance/evidence. Use **Field & asset filters…** for AND-connected rules on any stored property. Text operators are contains, equals, not_equals, present and missing. Numeric operators are <, <=, >, >= and numeric_equals with a declared unit. For example, field Temp_Max, operator <, value 80, unit C. Missing/invalid quantities never become zero; the response reports numeric unknowns. Search is case-insensitive for ordinary text, not an automatic manufacturer identity merge.

Asset filters distinguish symbol stored, footprint stored, model stored, all three captured in one coherent set, and incomplete references. Preference and generic/orderable identity can also be filtered. Predicates apply before pagination, not only to the visible page. The GUI displays 50 matches per page. CLI/API limits are 1–500; text matching is indexed but typed predicates can scan every text-matched candidate. This is not an O(1) large-catalogue guarantee. Up to 20 field predicates are supported; this catalogue filter language is distinct from the project's Boolean BOM query language.

A part's asset chips, preference, recorded lifecycle and stock observations are separate. Every colour has a text label and tooltip. **Stored does not mean qualified, preferred does not mean in stock, and a missing renderer does not mean a missing original file.** Existing catalogue-health semantics are unchanged: there is no new live supplier feed.

## 2. Harvest symbols, footprints and every assigned model

Choose **Harvest projects…** and enter explicit saved projects or directories. Keep asset capture selected. Review the returned summary and downloadable full plan before typing IMPORT. The summary exposes captured-asset counts and incomplete-reference findings; the complete plan contains every observation. Import writes the catalogue only; it never changes the scanned project or library. Save workspace is not required to commit a reviewed catalogue import.

### Sources supported by the resolver

| Asset | Supported source paths |
|---|---|
| Symbol | Schematic's lib_symbols cache; local modern .kicad_sym libraries resolved through project/global sym-lib-table and configured roots; supported local inheritance chains are flattened into an independent captured definition |
| Footprint | Unambiguously UUID-mapped saved .kicad_pcb footprint, including board-local edits; local .pretty/.kicad_mod via project/global fp-lib-table, configured roots, and standard KiCad locations; a directly linked supported embedded .kicad_mod payload |
| 3D originals | Absolute or relative local paths; project/native environment variables including KIPRJMOD and KICAD10_3DMODEL_DIR; configured model roots/path aliases; kicad-embed:// payloads in supported footprint, board or schematic ownership scopes |

Embedded model data is bounded base64/Zstandard with SHA-256 or supported KiCad modern/legacy MMH3 verification. Corrupt nearer-scope data cannot silently fall through to a similarly named file. A metadata-only nested reference can resolve an owner payload only with compatible identity/checksum. Decompression needs python-zstandard or an available system/KiCad Zstandard library; see setup below.

For footprints, **board_first** is the default: a saved board snapshot is chosen only when the full schematic instance path and footprint identifier agree. Otherwise the local library is attempted. **library_first** deliberately prefers the source library. One coherent source is captured per observation, not an arbitrary mixture of pad geometry from one source and models from another. The source and fallback reasons are recorded. Scan both configurations when intentionally collecting both edited-board and library alternatives.

Every declared model reference is considered, including hidden/inactive references and multiple STEP/VRML alternatives. Offsets, rotation, scale, visibility, model index, original URI, filename, source and checksum remain associated with that exact footprint snapshot. Two same-named files with different bytes remain separate. Identical bytes are stored once by SHA-256, while each usage keeps its own transform and provenance.

### Custom locations

The harvest dialog includes optional data-only **Asset resolution options**. The same object works as CLI --asset-config. Forward slashes work in Windows JSON:

```json
{
  "symbol_roots": ["C:/EDA/Symbols"],
  "footprint_roots": ["C:/EDA/Footprints"],
  "model_roots": ["C:/EDA/3D"],
  "variables": {"COMPANY_MODELS":"C:/EDA/3D"},
  "path_aliases": {"LEGACY":"C:/EDA/Legacy3D"},
  "footprint_source":"board_first"
}
```

KIPRJMOD cannot be overridden. Saved project-variable edits are included. Workspace/variant-only expressions are not a substitute for native path definitions. Unresolved variables, ambiguity and absent files remain findings. Windows absolute paths in a project moved to Linux/macOS may need an explicit native path correction or alias; the resolver does not guess an unrelated basename. Configured roots are not a whole-disk recursive search.

### What is retained

The catalogue owns the captured bytes, not just a shortcut to the original location. Preview and export continue after the original project/library/model directories are moved or removed. Capture strips embedded fonts and unrelated attachments. Symbols are independent stored definitions, optionally flattened from inheritance, not byte-identical copies of an entire multi-symbol source library. Model originals are byte-identical and separately checksum-verified.

Each observation set binds symbol, footprint and model references to its project, instance, reference and variant. Part revisions retain earlier assets and sets. Re-harvesting does not silently overwrite curated metadata; existing conflict/review rules still apply. Source file, library table, path-setting and model changes between scan and import invalidate the reviewed plan.

Limits: 64 MiB per stored asset, 192 MiB per parsed native source document, 256 MiB unique captured bytes per scan, 200 model references per observation set. CLI asset-bearing harvest-plan input has a dedicated 384 MiB limit; ordinary CLI/API inputs retain 20 MiB. Large plans should be saved to a file, not pasted into a browser or terminal. Split large project collections into reviewed scans. Cancellation does not delete or replace existing catalogue entries.

## 3. Inspect a search result

Choose **Preview S / F / 3D**. The inspector has Symbol, Footprint, 3D model and Sources tabs, searchable metadata, a part-revision selector and a source-set selector. Different observed assemblies are kept distinguishable. Changing tabs is read-only. Download original saves the selected captured file; it does not open an arbitrary source path.

| View | Implemented inspection controls and boundaries |
|---|---|
| Symbol | Common/selected units, normal/alternate body style, supported rectangles/circles/arcs/polylines, pin numbers/names and text; pan, zoom, Fit and labels toggle |
| Footprint | Supported copper pad shapes, drill indications, silkscreen/fab/courtyard primitives and text; local-coordinate inspection, pan/zoom/Fit and labels toggle |
| 3D | Rotate, wheel/keyboard zoom, Fit, Front/Top/Side/Isometric, selection among every model reference; shows one model in its own coordinates |
| Sources | Exact captured hashes, source set, original references/transforms and issues, plus downloads of stored files |

The 3D view does **not** apply the footprint's placement/scale/rotation to an overlay and does not prove mechanical alignment. Those transformations are retained for native export. Size is fit to the viewport, not a calibrated measurement tool. STEP uses neutral tessellation colours; original STEP data is not changed. Text rendering uses system fonts, not embedded proprietary font files.

Keyboard: focus a 2D viewer, use arrows to pan, +/− to zoom and Home to Fit. In 3D, arrows rotate, +/− zoom, Home resets. Mouse drag pans 2D or rotates 3D. Screen-reader/comprehensive accessibility certification is not claimed.

### Formats and optional setup

Storage recognizes .step, .stp, .stpz, .stepz, .wrl, .wrz, .stl, .obj, .iges, .igs and .brep. Supported self-contained VRML97/STL/OBJ previews use the included parser. STEP/IGES/BREP tessellation uses the optional OpenCascade wrapper. Compressed model preview supports a bounded gzip or single-file ZIP container, not every vendor archive convention.

Use **Preview engine status**, or CLI doctor, to see the running Python interpreter and detected modules. From the distribution directory, install optional support with the same interpreter:

```powershell
# STEP/IGES/BREP preview plus portable embedded-model decoding:
py -3 -m pip install -r .\wayricad_bom_studio\requirements-preview.txt

# Only embedded-model decoding, without the larger CAD dependency:
py -3 -m pip install -r .\wayricad_bom_studio\requirements-assets.txt
```

The packages are pinned: cadquery-ocp 7.9.3.1.1 and zstandard 0.25.0. The CAD dependency and its transitive dependencies may be large. Installation is explicit, requires package availability, and is never run by the application. KiCad's managed plugin environment may use a different interpreter from py -3; use the interpreter shown in Preview engine status. Restart WayriCAD after installation. A missing/incompatible optional module produces an explanatory preview failure; capture and original download remain available.

The renderer uses WebGL where available, with a 5,000-triangle Canvas2D fallback. Conversion is isolated in a cancelable subprocess with a 60-second time limit and geometry/output bounds (100,000 triangles, 300,000 vertices). POSIX resource limits are additional guards; Windows has no equivalent memory job-object limit in this release. This is not a malware sandbox. Inspect only trusted local CAD sources.

Unsupported native primitives (for example custom pad outlines, text boxes and images) are omitted or simplified with visible warnings. Pin decorations, drill offsets and exact native font/line rendering are limited. Texture/material auxiliaries and external geometry references are **not** automatically harvested or followed. Detected VRML Inline/texture/script, OBJ material-library or STEP external-document declarations make completeness unresolved; originals are retained, and strict native export is blocked. Prefer self-contained model files. Legacy .lib/.mod formats and arbitrary remote URLs are not silently converted/downloaded.

## 4. Export a reusable native library, including models

Select catalogue records and choose **Export selected native library**, or export the chosen set from its inspector. The GUI defaults to requiring complete captured references. A part with several distinct usable observations needs an explicit set choice; the exporter never chooses a random geometry revision.

The ZIP contains:

```text
WayriCAD.kicad_sym
WayriCAD.pretty/*.kicad_mod
WayriCAD.3dshapes/<SHA256>.<original extension>
catalog-data.json
manifest.json
README.txt
```

Symbols are relinked to exported footprints; each captured model reference is rewritten to the corresponding exported original file while retaining its transform and visibility. Default model paths are ${KIPRJMOD}/WayriCAD.3dshapes/…; extract at the project root and add the symbol/footprint libraries in KiCad under nickname WayriCAD. For a shared global library, use a configured path-variable prefix such as ${WAYRICAD_LIBRARY}/WayriCAD.3dshapes at export and configure that variable in KiCad. Changing the prefix alone does not configure KiCad.

The manifest lists file hashes, chosen revisions/sets and incomplete references. Partial export is a deliberate choice; it retains explicit unresolved links and warnings. CLI requires --require-complete to opt into strict export, unlike the GUI's checked default. No library tables, source projects, source model files or existing output files are overwritten.

Front-side saved board footprints are detached from board placement for library export. **Back-side board snapshots are retained and can be inspected, but library export refuses guessed front-side normalization.** Re-harvest with library_first or normalize/save an appropriate source footprint in KiCad. This is separate from 3D orientation in the preserved source reference.

A native library ZIP is not a full engineering-database backup. It excludes authentication secrets and does not carry the full review ledger/inventory history as a restored database. Metadata export is also not a full backup. Close WayriCAD and back up the whole catalogue directory. Review redistribution rights for proprietary or third-party symbol/footprint/model assets before sharing.

## 5. CLI parity

The existing 33 top-level command families remain. New catalogue subcommands are **assets**, **preview** and **asset-export**; search, harvest and native-export gained asset options. Commands work without a project argument except harvest, which takes explicit source projects/directories.

```powershell
$cli = ".\wayricad_bom_studio\cli.py"
$library = "$HOME\Documents\WayriCAD_Catalog"

py -3 $cli catalog search --library $library --query "10k" --has-asset all3
# Copy the exact id from a chosen result, not a reference designator:
$partId = "p_REPLACE_WITH_THE_RETURNED_ID"
py -3 $cli catalog assets --library $library --id $partId
py -3 $cli catalog preview --library $library --id $partId --kind symbol --format svg --output ".\symbol-preview.svg"
py -3 $cli catalog preview --library $library --id $partId --kind model --model-index 0 --output ".\model-mesh.json"
py -3 $cli catalog native-export --library $library --ids $partId --require-complete --output ".\Reusable_Part.zip"
```

preview JSON contains generated SVG or mesh plus warnings, hashes and the chosen source set. It does not launch a GUI or KiCad viewer. asset-export --hash HASH --output new.step downloads the exact stored model; use the original extension. Native symbol downloads are wrapped in a .kicad_sym container. Existing paths are refused, and ordinary automation outputs remain forbidden from writing native design files. Use --revision and --set-id for an earlier part revision/set during inspection. Native library export currently uses the current part revision, with explicit current-revision set choices.

The normal data-only CLI envelopes and exit codes apply: 2 for invalid input/unsupported preview, 3 for policy findings where requested, 4 for I/O/output conflicts, and 130 for interruption. Preview conversion is not a manufacturing release gate. See CLI_REFERENCE.md for complete commands and filters.

## 6. Upgrade and validation boundary

Back up the whole catalogue directory and project sidecar while the application is closed. Install the complete v0.7 package, not a patch. Existing v0.6 records remain readable but show **not_captured** for absent model history. **Re-harvest the source projects to populate 3D assets**; a software update cannot recover files never stored. Do not downgrade an updated catalogue into v0.6.

TRY_ENGINEERING_SAMPLE_WINDOWS.bat now includes original, explicitly synthetic VRML and STEP resistor-like geometry. It makes a temporary project/catalogue and creates no reviewer accounts/default passwords. Use Library & control, search DEMO-R0603-10K, and inspect the previews. Values, geometry, masses and stock in this example are not manufacturer data.

Tests exercised real conversion, original-byte downloads, stored-file independence after deleting sources, GUI controls through the HTTP bridge, HTTP authentication and CLI operations. **KiCad itself, native model/library loading, Windows/macOS installation and KiCad 11 were not executed.** This environment used Canvas2D fallback; the WebGL path is implemented but remains target-browser acceptance. Direct browser navigation was blocked by managed policy. Read TEST_REPORT.md for actual counts and boundaries.
