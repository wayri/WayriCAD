# WayriCAD 3.6.8

This release adds the independent **Variant Manager 0.6.0** package and updates
**Project Fusion to 0.9.6**. Pin Extractor 3.6.8 updates the suite capability and
dependency registries. Other PCM packages retain their published versions.

Fusion identifies a whole project, child sheet occurrence, standalone schematic
or PCB-only source from the selected file. Multiple owners or repeated sheet
occurrences remain explicit choices. Scope can still be overridden. The sheet
catalogue avoids full import discovery and uses bounded content-hashed syntax
caching; fresh native acceptance checks remain mandatory. A synthetic 100-sheet
occurrence/20-symbol example measured 0.024 s for catalogue listing versus
1.983 s for full discovery. This measures scope listing, not merge performance.

A dedicated layout-only viewport previews a source PCB inside an existing
working project. Imported footprints become Board Only items with isolated nets
and fresh identities. The target schematic and configuration stay unchanged.
The target owns the outline/stackup; outer faces are preserved and vias must be
through holes. New native DRC or unconnected findings reject the candidate.
Apply Review opens independently so target editors can close before backed-up
offline application. Unsupported image/embedded payloads remain rejected.

Variant Manager compares local native instance states and shows saved-board
assembly overlays, with top/bottom filters and cross-selection. It supports
create, duplicate, rename, bulk delete/edit, merge with explicit conflict policy,
swap, Default promotion and selected-variant recovery. The CLI previews JSON
operation batches and exports review evidence. Applying requires closed project
editors, fresh sources and a mandatory verified backup. PCB geometry/routing
remains unchanged; promoted footprint/presence changes need KiCad's Update PCB
from Schematic. Parent-sheet flags remain explicit and reused-instance Default
conflicts are refused.

Focused native validation uses Windows and KiCad 10.0.6: schematic/netlist/BOM/PDF
serialization, saved-project geometry/parity/DRC checks and standalone wx
windows. Linux/macOS native GUI qualification and every installed-editor workflow
remain unverified. These are testing packages, not manufacturing sign-off.

Install the independent Variant Manager and Fusion PCM ZIPs, or refresh the
WayriCAD PCM repository and restart PCB Editor. Read the
[Variant Manager guide](../variant_manager_plugin/README.md) and
[Fusion guide](../project_fusion_plugin/README.md) before applying saved-file changes.
