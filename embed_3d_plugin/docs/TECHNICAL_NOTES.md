> **0.4.0 navigation:** the new default is the unified component window documented in `UNIFIED_WORKSPACE.md`. This document retains the earlier backend/advanced workflows; their separate dialogs are under **Options → Standalone library / live-board tools…**. See `TEST_REPORT.md` for current validation.

# Technical notes and source references

## Implementation

`sexpr.py` is a span-preserving reader, not a general KiCad writer. It locates direct footprint `model` entries and `embedded_files` entries, treats pipe-delimited Base64 as opaque, and applies disjoint text edits. Every token except model reference names and embedded-file blocks must remain identical. Each model's text after its filename must remain byte-exact when processing saved files.

`codec.py` writes Zstandard frames and Base64, with SHA-256 verification. KiCad 10's embedded-file reader explicitly accepts 64-character SHA-256 checksums and upgrades them to its internal MMH3 checksum. New entries use SHA-256; this avoids introducing an unverified hash implementation. Native compression loads libzstd only from application/system locations. No downloaded native binary is bundled. A raw-block Zstandard implementation provides a compatible but larger fallback. Its output was independently decoded with the system libzstd in automated tests.

`core.py` resolves already-linked source files, deduplicates repeated payloads by generated name, preserves model transforms and creates reversible manifests. Generated names contain a full SHA-256 to prevent different contents with the same basename from colliding. Identical bytes with different original basenames are not globally deduplicated by this version. Sidecar/assembly dependency analysis is deliberately limited, not a complete CAD graph traversal.

`storage.py` creates backups before mutation, stages same-directory temporary files, replaces each file atomically, and verifies read-back. It detects modification since preview and subsequent edits before restore. The manifest is a recovery journal, not a filesystem-wide atomic transaction.

`native.py` uses `PCB_IO_KICAD_SEXPR(0).Format` to serialize complete footprints **with their embedded data**, then `Parse` and native reserialization to validate prepared updates. `CopyFrom` is not used because the inherited BOARD_ITEM implementation does not provide a complete footprint replacement. Live operations use `SwapItemData`, preserve the top-level footprint identity and parent group, restore child net pointers by UUID during preflight, and compare complete non-embedding native output before mutation. Unsupported native round trips fail closed.

Old child objects are kept alive until KiCad's `RunActionPlugin` wrapper has rebuilt the view and selection. Mutation stays inside `Run`; `wx.CallAfter` is used only for scan progress, completion notification and deferred release, not for a separate untracked edit transaction. Native live undo/redo has **not** been validated by executing KiCad here.

`ui.py` uses stock wx controls, the user's native theme, a single model checklist and primary action, progressive path settings, keyboard-accessible buttons, and a separate portable-export action. It does not implement a second 3D rendering engine or inject changes into a Footprint Properties dialog that is currently open.

`plugin.py` is a KiCad 10 legacy SWIG ActionPlugin. IPC is not required. This is intentionally version-limited to KiCad 10.0.x in PCM metadata; no KiCad 11 compatibility is claimed.

## Important native storage distinction

A standalone `.kicad_mod` can contain the model's embedded bytes. When a footprint is on a board, KiCad can consolidate the payloads into a board-wide pool on save. A board's embedded pool alone is not the same as an updated library footprint. Portable export reconstructs footprint-owned entries before using KiCad's library writer and checks that every exported model has a payload. Export normalizes board-instance placement into library form using KiCad; unexpected changes to model transforms cause export to stop.

## Primary sources consulted, 9 September 2026

- KiCad 10 PCB Editor manual — “Embedded files”, “Editing Footprint Properties”, and 3D models:
  https://docs.kicad.org/10.0/en/pcbnew/pcbnew.html
- KiCad 10 embedded-file implementation — `CompressAndEncode`, `DecompressAndDecode`, `WriteEmbeddedFiles` and SHA-256 compatibility:
  https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/common/embedded_files.cpp
- Native PCB/footprint serializer — formatter control flags, footprint data emission, board-pool consolidation, native library save:
  https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.cpp
- `BOARD_ITEM::SwapItemData` and base `CopyFrom` behavior:
  https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/board_item.cpp
- `FOOTPRINT::swapData` and child-parent rebinding:
  https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/footprint.cpp
- KiCad native action wrapper — undo snapshot, `RunActionPlugin`, `RebuildAndRefresh`:
  https://raw.githubusercontent.com/KiCad/kicad-source-mirror/10.0/pcbnew/python/scripting/pcbnew_action_plugins.cpp
- Python API signatures for the native serializer and footprint:
  https://docs.kicad.org/doxygen-python-10.0/classpcbnew_1_1PCB__IO__KICAD__SEXPR.html
  https://docs.kicad.org/doxygen-python-10.0/classpcbnew_1_1FOOTPRINT.html
  https://docs.kicad.org/doxygen-python-10.0/classpcbnew_1_1BOARD__ITEM.html
- ActionPlugin discovery and runtime:
  https://dev-docs.kicad.org/en/apis-and-binding/pcbnew/index.html
- PCM package structure and v2 metadata:
  https://dev-docs.kicad.org/en/addons/index.html

The linked stable source branch may change after this release. Source inspection is not the same as native execution. No KiCad source files or compiled KiCad components are included in this distribution.
