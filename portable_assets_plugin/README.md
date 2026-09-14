# WayriCAD Portable Assets 3.0.0

A KiCad 10 ActionPlugin for making a project self-contained without depending on the original footprint, symbol, or 3D-model library installation. The menu action launches an isolated GUI process and passes the active board path directly.

## What it does

### Make Portable

The **Make Project Portable** operation:

1. Reads the **actual placed footprint snapshots from the `.kicad_pcb`**, rather than trusting that the original library still exists.
2. Creates a project-local footprint library at:
   - `.portable_assets/Portable.pretty/`
   - nickname: `PortableAssets`
3. Rewrites each schematic `Footprint` property and each PCB footprint library link to `PortableAssets:<snapshot>`.
4. Resolves 3D model paths from project-local paths, `${KIPRJMOD}`, standard KiCad environment variables, absolute paths, and direct HTTP/HTTPS URLs.
5. Embeds each resolvable STEP/WRL model **inside the footprint itself** using KiCad's native `kicad-embed://...` Embedded Files representation.
6. Creates project-local symbol snapshot libraries from the schematic's `lib_symbols` cache and relinks placed symbols to `Portable_<original-nickname>:<symbol>`.
7. Updates `fp-lib-table` and `sym-lib-table` with `${KIPRJMOD}`-relative entries.
8. Optionally mirrors generated `.kicad_mod` / `.kicad_sym` source files into the **native Embedded Files collections of both the main schematic and PCB** as a recovery vault.
9. Writes a `.portable_assets/manifest.json` with the reference-to-footprint mapping and unresolved model list.
10. Creates timestamped backups and uses atomic file replacement.

The default mode creates one exact footprint snapshot per reference (for example `L2__L_Taiyo-Yuden_MD-5050.kicad_mod`). This deliberately preserves per-instance footprint edits that might exist only in the layout.

### Embedded Vault

The vault stores source-library files inside the design's native `embedded_files` section. If `.portable_assets` is lost during project transfer, **Restore .portable_assets from Embedded Vault** reconstructs the local libraries.

The active footprint link remains `PortableAssets:<name>` rather than `kicad-embed://...`. This is intentional: KiCad has had a KiCad 10 issue where a footprint embedded into a schematic symbol could be referenced by a `kicad-embed://` URI but **Update PCB from Schematic** would not instantiate it. The local-library + native-vault approach remains portable while avoiding that failure mode.

For 3D models, the active model URI is footprint-scoped `kicad-embed://...`, because KiCad resolves a model embedded directly in the footprint while board-level embedded model references have had a separate resolution limitation.

### Repair Missing Footprints

The **last tab** is **Repair Missing Footprints**.

If a schematic still says something such as:

`SomeLibrary:Inductor_XYZ`

but that library no longer exists, while `L2` is still present on the PCB, the plugin:

1. Finds `L2` in the schematic.
2. Finds the matching `L2` footprint snapshot already stored inside `.kicad_pcb`.
3. Extracts that complete footprint into `.portable_assets/Portable.pretty/L2__Inductor_XYZ.kicad_mod`.
4. Removes board-instance-only data such as the top-level placement, board UUID/path, and pad net assignments.
5. Preserves pads, custom pad geometry, footprint graphics on all layers, silkscreen, fabrication, courtyard, zones/groups, attributes, and 3D model definitions.
6. Embeds resolvable 3D models into the recovered footprint.
7. Changes the schematic Footprint field to `PortableAssets:L2__Inductor_XYZ`.
8. Changes the board snapshot's library link to the same project-local footprint.

This means a missing original `.pretty` library is not fatal if the desired footprint is already present in the board file.

## Installation (KiCad 10)

Install **WayriCAD Portable Assets** from the WayriCAD repository in KiCad's Plugin and Content Manager. For a manual installation, copy the entire package into the KiCad ActionPlugin folder.

Typical Windows location:

```text
C:\Users\<you>\Documents\KiCad\10.0\3rdparty\plugins\wayricad_portable_assets\
```

Typical Linux location:

```text
~/.local/share/KiCad/10.0/3rdparty/plugins/wayricad_portable_assets/
```

Typical macOS location:

```text
~/Documents/KiCad/10.0/3rdparty/plugins/wayricad_portable_assets/
```

Restart KiCad. The action appears in **PCB Editor > Tools > External Plugins** and uses the active board path without waiting for IPC environment registration.

Dependencies:

- `kicad-python`
- `wxPython` supplied by KiCad's bundled Python runtime
- `zstandard`

The embedded-file codec also contains a native `libzstd` fallback, so systems where KiCad/system Zstandard is visible can still encode/decode native Embedded Files if the Python `zstandard` import is unavailable.

## Safe workflow

Because KiCad 9/10 does not expose all schematic/native Embedded Files manipulation through the IPC API, the plugin performs the final operation as a transactional edit of KiCad's S-expression project files.

Recommended flow:

1. Open PCB Editor and launch **Portable Assets**.
2. Click **Analyze Project** while the editors are open if desired.
3. Save your schematic and PCB.
4. Close Schematic Editor and PCB Editor. The Portable Assets window is a separate process and remains open.
5. Confirm that the lock indicator is clear.
6. Click **Make Project Portable**.
7. Re-open the project in KiCad and inspect the changed links / 3D view.

The plugin intentionally refuses Apply/Repair while project lock files are present. This prevents an open KiCad editor with an older in-memory copy from overwriting the plugin's disk changes on its next save.

Backups are placed under:

```text
.portable_assets/backups/YYYYMMDD-HHMMSS/
```

## How 3D resolution works

The resolver attempts, in order:

- existing `kicad-embed://` link: left as-is
- direct `http://` / `https://` model URL: downloaded if network access is enabled
- `${KIPRJMOD}` expansion
- environment-variable expansion such as `${KICAD10_3DMODEL_DIR}`
- absolute path
- path relative to the project
- path relative to a resolvable original project footprint library
- user-added model search roots (core option; UI extension point)

If a model cannot be resolved, its existing model link is **left untouched** and reported instead of being replaced with a broken embedded URI.

## Files created

```text
<project>/
├── fp-lib-table                         # adds PortableAssets
├── sym-lib-table                        # adds Portable_<nickname> libraries
├── .portable_assets/
│   ├── manifest.json
│   ├── Portable.pretty/
│   │   ├── L2__....kicad_mod
│   │   └── ...
│   ├── symbols/
│   │   ├── Portable_Device.kicad_sym
│   │   └── ...
│   └── backups/
│       └── YYYYMMDD-HHMMSS/
└── ...
```

## Native embedding implementation

The plugin writes the same Embedded Files structure used by KiCad:

- URI: `kicad-embed://<name>`
- Zstandard compression, level 15
- Base64 MIME wrapping at 76 characters
- KiCad's MurmurHash3 x64 128 checksum seed `0xABBA2345`
- model files classified as `type model`; generated source libraries as `type other`

The S-expression engine is source-span based: it changes targeted forms/atoms and avoids reformatting the entire schematic or board.

## Known limitations / conservative behavior

- **Apply must be done with the editors closed.** Analyze can be done while open.
- Footprints that exist in the schematic but have **never been placed on the PCB** cannot be reconstructed from PCB geometry. The plugin can only repair from a footprint snapshot that actually exists in `.kicad_pcb`.
- A remote footprint itself does not need to be downloaded when it is already placed: the board contains the full footprint geometry, so the board is treated as the authoritative snapshot. This is a feature for portability.
- Direct HTTP/HTTPS 3D URLs are supported. Proprietary remote-library protocols that do not expose a model as a resolvable file/URL may remain unresolved.
- Back-side footprints are captured as the actual board snapshot. This maximizes preservation of the placed design; review a recovered footprint before reusing it as a generic library part in a different design.
- The tool currently targets modern KiCad 9/10 S-expression projects. KiCad 10 is the intended environment.
- The plugin does not delete original libraries or the original source files.

## Development / standalone launch

The entrypoint can also be run directly from the plugin's Python environment:

```bash
python portable_project_action.py --project /path/to/project
```

This is useful for applying the operation without opening PCB Editor first.

## Suggested validation before using on an important project

Run it first on a Git copy/branch of a representative project and verify:

- Schematic opens without rescue dialogs.
- `Footprint` fields point to `PortableAssets:*`.
- PCB footprints retain geometry and reference/value placement.
- 3D Viewer shows embedded models.
- Update PCB from Schematic does not unexpectedly replace custom per-instance geometry.
- The project opens correctly after copying the entire project folder to a clean machine/user profile.

The plugin already makes backups, but version control remains the best way to review the exact changes.
