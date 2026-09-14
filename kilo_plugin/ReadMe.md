> **Consolidated in 3.1:** Install [WayriCAD Project Library](../embed_3d_plugin/README.md). This source API remains for older scripts; the separate PCM tool is retired.

# Kilo — KiCad Localizer Help

Kilo makes KiCad 10 projects and design blocks portable by collecting their
footprints and 3D models into project-local libraries.

## Before using Kilo

1. Save the project in every open KiCad editor.
2. Use **Dry Run** before an operation that changes files.
3. Review the planned files, mappings, conflicts, and warnings.
4. After execution, close and reopen or reload affected Schematic and PCB
   Editors. KiCad may retain older in-memory file and library-table content.

Kilo never modifies KiCad's global library tables. New transactions, backups,
reports, and restore history are stored in the project's `.kilo/` directory.

## Localize Project

Use **Localize Project** to copy every resolvable project footprint into one
project-local `.pretty` library. Models can be copied as local files or embedded
inside the localized footprints.

1. Select the project directory.
2. Choose **Scan** to inspect dependencies.
3. Choose **Dry Run** and review the action list.
4. Choose **Execute** after saving the project.

If a source library is unavailable but its footprint exists on the board, Kilo
can recover the board's saved footprint geometry.

## Design Block Packager

Select a `.kicad_block` directory to embed its footprint, model, attribution,
and package-manifest payloads into its schematic. Use an output directory to
create a portable copy without changing the source block.

## Design Block Installer

Select a Kilo-enabled `.kicad_block` and a destination project. Kilo verifies
all payload hashes, installs project-local footprint and model libraries,
rewrites the installed block's footprint assignments, and registers the
project-specific design-block library.

Packages created with the former BlockPack identifiers remain readable.

## Validate / Repair

Validation is read-only and checks footprint resolution, model references,
project library tables, transaction manifests, and installed package hashes.
Repair always exposes a dry-run plan before writing.

## History / Restore

**Links-only** restore is the safest default. It restores recorded dependency
links while preserving unrelated edits. **Original-files** restore replaces
files byte-for-byte and refuses changed files unless force is explicitly
selected.

Kilo discovers restore points under both `.kilo/` and the legacy
`.kicad-blockpack/` directory. Legacy data is read without being migrated or
deleted.

## Command line

The same workflows are available from a terminal:

```text
kilo --help
kilo scan-project <project>
kilo localize-project <project> --dry-run
kilo validate-project <project>
kilo unlocalize-project <project> --dry-run
kilo package-block <block.kicad_block> --dry-run
kilo install-block <block.kicad_block> --project <project> --dry-run
```

## Getting more diagnostic information

Use **Export Log** in any workflow tab. Successful write operations also create
JSON reports and human-readable logs under `.kilo/reports/` and `.kilo/logs/`.
Keep the associated `.kilo/backups/` directory for as long as restoration may
be required.
