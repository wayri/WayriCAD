> **0.4.0 navigation:** the new default is the unified component window documented in `UNIFIED_WORKSPACE.md`. This document retains the earlier backend/advanced workflows; their separate dialogs are under **Options → Standalone library / live-board tools…**. See `TEST_REPORT.md` for current validation.

# PCB package: embedded footprint definitions + models — 0.2.0

## The separate option

Open **WayriCAD Embed3D → Package PCB…**. This workflow creates a **new packaged PCB copy in a new folder**. It does not overwrite, swap or silently migrate the active PCB, original libraries, schematic or global library table. Ordinary **Embed N models** remains a separate live-board/file operation.

The package contains all placed footprints, including footprints with no 3D model. Optional supplied `.kicad_mod` files or `.pretty` directories can also be archived and registered. Supplied definitions can be archived in a PCB even when it has no placed footprints.

### Workflow

1. Fix unresolved models in the main dialog using **All board footprints**, **Models folder…**, **Find missing…**, or **Locate model…**. The package dialog reuses those reviewed per-source repairs. Packaging does not permit an incomplete model set.
2. Open **Package PCB…** and keep **Use footprints as placed on the board** for the closest match to the current layout. This archives actual as-placed definitions, including custom pad/graphic changes, rather than fetching an unrelated global-library version.
3. Optionally add supplied footprint files or a `.pretty` library. Select **Prefer supplied definitions with matching Library:Name IDs** to use supplied definitions as the link targets for matching placed instances. **Set source ID…** assigns the exact original library ID when a filename/folder is not the same as its KiCad nickname. Matching is exact; a bare similar name is not enough. Duplicate supplied source IDs are blocked in matching mode.
4. Click **Preview package**. Inspect the target links and any model errors. Imported footprints with bad model paths should first be repaired/embedded through the main dialog's saved-footprint mode.
5. Click **Create new PCB package…**, choose a parent directory and a new folder name, review the confirmation, and open the resulting `.kicad_pcb` after creation. The old board remains open and unchanged until you choose the new one.

All board instances are included; this is not a selected-only package that silently leaves other models external. Each as-placed instance has a distinct library definition, so two instances of the same nominal footprint with different board edits are not incorrectly collapsed.

## Where the data lives

The new PCB's **Board Setup → Embedded Files** contains actual compressed/encoded file data, not merely paths:

| Entry | Purpose |
|---|---|
| `model__<SHA256>.step` (or the original format's extension) | Shared board-level 3D-model bytes |
| `WayriCAD_Embed3D_fp__<SHA256>.kicad_mod` | Reusable footprint snapshot, stored as a native `other` embedded file |
| `WayriCAD_Embed3D_manifest.json` | Definition/instance mapping, original/new footprint IDs, source model references and content hashes |

The footprint model references on the PCB use native `kicad-embed://...` URIs. The board's original model offset, scale, rotation, opacity, visibility and any other model-suffix settings remain in the model entries. They are not baked into or applied twice to the geometry. Footprint ID and embedding-related spans are patched; pads, pad nets, positions, orientations, copper layers, tracks, zones and other board fields are checked for preservation.

Repeated newly introduced model content with the same format extension shares one canonical payload even when source basenames differ. Pre-existing board attachments are preserved, so an already-embedded board can retain old payload names alongside newly canonicalized ones. Distinct format extensions are not conflated even when byte data happen to be identical.

Footprint definitions are normalized for library use with KiCad's native `FootprintSave`, which handles board orientation/side and removes board-net association from library definitions. The model settings are checked before and after this normalization. As-placed board geometry remains untouched. If native normalization fails the checks, the package is stopped rather than weakening the checks.

## The native library limitation

A KiCad 10 native footprint-library URI points to a real filesystem directory of `.kicad_mod` files. Attaching a `.kicad_mod` to a PCB does **not** automatically make `kicad-embed://that-file.kicad_mod` a valid `Library:Name` lookup target. The plugin does not write such an unsupported library URI.

Instead, the package reconstructs `WayriCAD_Embed3D_<board>.pretty` from the embedded snapshots and registers it in a project-local `fp-lib-table` using:

```text
${KIPRJMOD}/WayriCAD_Embed3D_<board>.pretty
```

Placed footprint IDs are relinked to that library in the **new PCB**. Each materialized library footprint is hydrated with the model bytes it needs, so opening it in the Footprint Editor does not require loose external STEP/WRL files. The canonical source for reconstruction is inside the PCB; the `.pretty` directory is the native-compatible working representation.

Keep the package folder together for ordinary library operations. Moving only the PCB retains its placed geometry and board-level model payloads, but its external library table/working directory must be reconstructed for library lookup/edit/update operations. **This is not a directly mountable, single-file footprint-library backend.**

## Rebuild after moving only the PCB

Use **More → Rebuild embedded library from PCB…** and select the saved packaged PCB. The plugin verifies snapshot/model hashes, reconstructs the local `.pretty` directory next to that PCB, and adds/preserves the corresponding project library-table entry. Reopen the project so KiCad reloads its table.

Rebuild does not change the PCB. It creates missing library files, permits byte-identical existing files, and **refuses to overwrite later/different edits**. It preserves unrelated table entries and refuses a library nickname already mapped to another location. A table backup/journal is created before writes. Caught failures roll back newly published files and table changes where possible; a multi-file rebuild is not power-loss-atomic. Exclusive file publication uses same-filesystem hard links, normally available on local NTFS/ext4/APFS filesystems. A filesystem without that capability fails safely; use a local filesystem or the initially generated package folder.

The optional source CLI works without KiCad:

```text
python -m embed_3d_plugin inspect-board "C:\Project\board.kicad_pcb" --json
python -m embed_3d_plugin rebuild-library "C:\Project\board.kicad_pcb"
python -m embed_3d_plugin rebuild-library "C:\Project\board.kicad_pcb" --apply
```

The first rebuild command is a dry run. `--project` selects an existing destination project folder when needed. CLI archive checks do not execute KiCad's parser or renderer. PCB package creation itself uses the GUI/native bridge for proper footprint normalization; it is not exposed as a pure-Python schematic/layout conversion command.

## Supplied definitions: relink, not replace

In supplied-definition mode, matched instances link to the supplied library definition, but their current PCB pad geometry, nets, placement and model settings are retained. The original as-placed definition is still archived separately for recovery. The supplied library file retains its own intended geometry and model settings; it may differ from the current instance. A later **Update Footprints from Library** is a separate potentially geometry-changing operation and must be reviewed.

The default as-placed mode avoids this mismatch by building the library definitions from the actual board instances.

## Safety and scope

Package creation is new-output-only. Source model files are never deleted or moved on disk; “move models to the board pool” describes where the copied embedded payloads are stored inside the new PCB. Input footprint bytes and model hashes are rechecked after preview. Publication is staged, native-parsed and round-tripped for model settings/IDs/payload retention before the new output directory is published. A failed check does not replace the original board.

Saved `.kicad_pro` and `.kicad_dru` sidecars are copied when present. Unsaved settings in another KiCad dialog are not captured from those files. The package scope is footprints and their linked model files—not every external project resource. Schematics, schematic symbol libraries, external drawing-sheet paths and unrelated external dependencies are not automatically migrated. Existing embedded resources are preserved where the native checks permit them.

**Schematic Footprint fields are not rewritten.** Updating the packaged PCB from the old schematic can restore old library IDs. The embedded/plain JSON manifest records the original and new IDs; deliberately synchronize the schematic fields in a separately reviewed operation before relying on bidirectional updates. No schematic is silently created, edited or copied.

File embedding does not change the licenses of the source footprints/models. Existing metadata is retained; comply with source-library licensing when distributing a package. Recognized external texture/Inline resources remain blocked, and unusual indirect STEP assembly dependencies are not exhaustively analyzed.

## Compatibility references and test limits

- KiCad 10 embedded files: https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- Native footprint-library cache directory loading and `FootprintSave`: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp
- Native embedded file types/format: https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/include/embedded_files.h

The 10.0 source branch was inspected, and pure-Python composition/reconstruction tests were executed. Native KiCad execution, GUI rendering, real STEP display, Windows installation and live-board undo remain unverified in this build environment. Three opt-in native package tests are supplied, including back-side/rotated and zero-model cases. Begin with a copied, small project.
