# WayriCAD Embed3D

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD Embed3D icon">

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#getting-started) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run embed-3d -- --help` |

CLI scope: Asset inventory, localization dry run and reviewed operations. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

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

Install the **Embed3D PCM ZIP from the latest release** using KiCad PCM **Install from File**. Enable the API in Preferences → Plugins. Local normalization and validation require KiCad 10 native Python; `WAYRICAD_KICAD_PYTHON` can select it. IPC is the forward integration path; KiCad 11 native acceptance remains unverified.

## Getting started

For the usual workflow, save the PCB and schematic, open Embed3D, and click **Scan**. Check the wanted component assets, then click **Preview embed + relink** and review the new-design output before **Apply preview**. This embeds checked assets and relinks the new saved design copy; source designs are unchanged. To take embedded assets back out as files, click **Preview unwind** and apply. The default destination is a unique folder under the project's `local/` directory. Unwind does not change the design; choose **Relink** under Options if a new externally linked design copy is also needed.

**Options & library tools → Localize entire project with backup** retains the full-project workflow. It keeps symbols, footprints and 3D models together in **`local/`**, or another relative project folder, and updates the saved project with a backup after a separate preview. Save and close project editors before that in-place operation. Settings remember the folder, additional model roots and explicit `NAME=FOLDER` path variables.

![Full-project localization preview with a generated example](help-project-library.png)

Advanced **Localize entire project with backup** preview, also shown in offline help. This is a generated example; this operation updates project files after review and editor closure.

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


## Resize the workspace and find help

The main workspace scrolls, so long component inventories and lower asset actions remain reachable in smaller windows. Resize the window for wider paths and tables; checked assets remain selected when the visible list is filtered.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.

## Implemented methods, provenance and validation

| Method | Inputs and outputs | Implementation, evidence and limits |
|---|---|---|
| S-expression inventory and identity | Saved schematic/PCB/library text becomes component rows keyed primarily by native symbol or footprint UUID, with reference-only matches kept separate when ambiguous. | [`scan_design`](workspace.py), the bounded parser in [`sexpr.py`](sexpr.py), and [`test_workspace.py`](tests/test_workspace.py). Shared sheet files are represented once because one edit affects all instances. |
| Asset resolution and content addressing | Model/library references plus explicit variables and roots resolve to bytes; embedded names and repeated payloads are keyed by SHA-256 and type. | [`Planner`](core.py), [`Resolver`](paths.py), and [`compose`](board_package.py). A digest establishes byte identity and staleness, not model authenticity, licensing or mechanical correctness. Compressed dependencies are inspected conservatively and missing files remain unresolved. |
| Selective embed/unbundle/relink | Checked symbol, footprint and model sets produce patched design copies, embedded payloads, extraction manifests and project-relative links. | [`prepare_operation`](workspace.py), [`embed_board`](workspace.py), and [`portability_io.py`](portability_io.py), covered by [`test_portability_io.py`](tests/test_portability_io.py) and [`test_unbundle.py`](tests/test_unbundle.py). The tool preserves model transforms but does not infer a replacement for an absent asset. |
| Board package reconstruction | Footprint definitions and models are canonicalized by content, footprint instances are associated by UUID, and a manifest records original IDs and payload hashes. | [`compose`, `recover` and `write_package`](board_package.py), with round-trip checks in [`test_board_package.py`](tests/test_board_package.py). Reconstruction verifies the generated library against the board; it is not a 3D collision or fit analysis. |
| Freshness, staging and publication | Preview records every input hash. Apply rechecks them, writes staged/temporary files, replaces individual files atomically and records before/after hashes. | [`WorkspacePlan.apply`](workspace.py), [`embed_files`](storage.py) and [`publish_design`](portability_io.py), tested by [`test_workspace.py`](tests/test_workspace.py) and [`test_core.py`](tests/test_core.py). A multi-file operation cannot be power-failure atomic; journals and conservative rollback make recovery reviewable. |
| Backup restore | A manifest-bound restore verifies backup bytes and restores only a target that still has the job's recorded output hash. | [`restore_files`](storage.py) and [`test_core.py`](tests/test_core.py). Later user edits are refused rather than overwritten. |
| Native normalization and acceptance | Optional KiCad-native workers normalize footprint/library material and validate candidate projects before publication. | [`native.py`](native.py), [`native_worker.py`](native_worker.py), and opt-in [`test_native_runtime.py`](tests/test_native_runtime.py). Pure-Python tests do not prove native KiCad compatibility; see the recorded [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md). |

### Technical background

- KiCad's [common S-expression syntax](https://dev-docs.kicad.org/en/file-formats/sexpr-intro/) and official [schematic](https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/) and [board](https://dev-docs.kicad.org/en/file-formats/sexpr-pcb/) formats define the serialized records this tool parses and patches.
- Python's [`hashlib`](https://docs.python.org/3/library/hashlib.html) documents the SHA-256 primitive used for content identity and freshness. It does not by itself provide signatures or trusted provenance.
