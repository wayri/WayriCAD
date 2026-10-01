# WayriCAD Embed3D

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD Embed3D icon">

## Capabilities

- Localizes symbols, footprints, and 3D models into a project-relative folder.
- Previews the exact files and links before applying a change.
- Updates schematic assignments, library IDs, PCB footprint IDs, and model addresses together.
- Writes staged, natively validated output with backups and rollback on failed publication.
- Supports project-copy upgrades, selective embed/unbundle/relink operations, and backup restore.
- Provides dry-run CLI localization and content manifests for managed assets.

## Limitations

- Local normalization and validation require KiCad 10 native Python; KiCad 11 native acceptance is unverified.
- Source project editors must be saved and closed before localization.
- Missing external models cannot be recreated from their filenames; complete localization requires their source folders.
- The workflow does not collect arbitrary SPICE models, datasheets, drawings, project resources, or independent top-level sheets.
- Native tests are opt-in, so pure-Python test results do not establish native compatibility.

## Overview

The default window is a selective asset workspace. It scans saved PCB and schematic files, lists components, and lets you check the symbols, footprints and 3D model sets to process. The existing `embed-3d` package identifier is retained for upgrades.

Install `WayriCAD-embed-3d-3.1.1-PCM.zip` using KiCad PCM **Install from File**. Enable the API in Preferences → Plugins. Local normalization and validation require KiCad 10 native Python; `WAYRICAD_KICAD_PYTHON` can select it. IPC is the forward integration path; KiCad 11 native acceptance remains unverified.

For the usual workflow, save the PCB and schematic, open Embed3D, and click **Scan**. Check the wanted component assets, then click **Preview embed + relink** and review the new-design output before **Apply preview**. This embeds checked assets and relinks the new saved design copy; source designs are unchanged. To take embedded assets back out as files, click **Preview unwind** and apply. The default destination is a unique folder under the project's `local/` directory. Unwind does not change the design; choose **Relink** under Options if a new externally linked design copy is also needed.

**Options & library tools → Localize entire project with backup** retains the full-project workflow. It keeps symbols, footprints and 3D models together in **`local/`**, or another relative project folder, and updates the saved project with a backup after a separate preview. Save and close project editors before that in-place operation. Settings remember the folder, additional model roots and explicit `NAME=FOLDER` path variables.

Full-project localization output contains a `.pretty` footprint library, `symbols/WayriCAD_Project.kicad_sym`, `models/`, and a content manifest. Project tables use `${KIPRJMOD}` links. Placed schematic footprint assignments, symbol IDs/cache keys, PCB footprint IDs and model addresses are updated together. Native footprint normalization and model-transform checks preserve placement. Schematic-only designs also collect assigned footprints.

Writes are staged and natively validated before publication. Replaced files are backed up under `.wayricad-backups/`; stale sources, conflicting unmanaged assets and modified managed libraries are protected. Failed publication rolls back. Repeated extraction keeps stable asset filenames.

The selective workspace's Options retains Embed all, separate Relink, combined Unbundle & relink, path and normalization settings, diagnostics, and live-board tools. The full-project window's **More → Upgrade a project copy** converts older schematic hierarchies using the local KiCad CLI, preserving legacy reference/unit/page records and power-net semantics and comparing native connectivity. The optional native **Advanced Live Assets** menu action retains tools requiring the actual PCB Editor context.

The checked 3D-model box applies to all model links on that component. Inspect its details before applying when a footprint has multiple model files. Search filters the list without changing checked selections.

```text
wayricad-library localize-project board.kicad_pcb
wayricad-library localize-project board.kicad_pcb --library-folder libraries/local --apply
wayricad-library localize-project board.kicad_pcb --model-root D:/models --var CERN=D:/models --allow-partial --apply
wayricad-library restore-local PROJECT/.wayricad-backups/BACKUP --apply
```

Without `--apply`, localization is a dry run. Exit 3 indicates explicitly retained unresolved assets. Restore verifies backup hashes and protects subsequent user edits. `python -m embed_3d_plugin --help` lists the retained embedding/extraction commands.

Unavailable external files cannot be recreated from a filename. [CERN's public library](https://gitlab.com/ohwr/cern-kicad-libs) excludes its 3D collection; supply the original model folder for complete localization of designs using those references.

From the repository root, run `python -m unittest discover -s embed_3d_plugin/tests` for regression tests. Native tests are opt-in and are not covered by a passing pure-Python test count. Original license notices remain in LICENSE. Older documents under docs describe the imported releases and are historical.
