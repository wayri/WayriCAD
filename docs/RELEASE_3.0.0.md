# WayriCAD 3.0.0 — testing release

WayriCAD replaces the previous suite with 22 independently installable KiCad packages, including BOM Studio and Embed3D from the supplied archives and three tools from the supplied development folder. The repository, package identifiers, release assets, documentation, action names and icons now use WayriCAD branding. Original copyright and third-party license notices remain intact.

## Design and review

Fanout and stitching use a compact settings rail, a large neutral canvas, and Preview / Apply actions. Advanced settings and candidate tables expand when needed. The preview shows footprint pad shapes and numbers, references, existing copper, proposed tracks, via copper and drill diameters, rejected positions and a millimetre scale. Drag to pan, scroll to zoom and double-click to fit.

Fanout adds a dedicated via-in-pad mode, distinct pattern choices, configurable angles and offsets, detected net-class filtering and an output copper layer selector. Changing the output layer includes a source via so the escape trace remains connected. Stitching checks real board outlines and cutouts, copper restrictions, layer spans, clearance and reference exclusions. Missing required geometry blocks generation instead of silently dropping the restriction.

Reviewed plans bind their settings and board state. Apply refuses stale plans; grouped writes retain recovery information if a mutation fails. Heater and magnetics placement reviews also remain non-mutating, and Bulk Label Editor applies reviewed values with stale-value checks and rollback.

Shared window headers are smaller. Routing, heater, magnetics, manufacturing, Embed3D and BOM workflows place the primary action beside their result and move secondary controls into tabs, collapsed sections or More menus. BOM Studio uses five primary views and an authenticated local browser fallback when an embedded desktop webview is unavailable. All application UI assets are local.

## Integrated applications

Advanced fanout now includes 45° and custom-angle spreading, straight-then-angled escapes, staggered rows, and differential-pair breakouts. Family presets cover DDR/GDDR, SERDES, PCI/PCIe, PXI/PXIe and LVDS with editable net filters. Paired candidates are rejected together on clearance, transition or generated-skew failures; every bend and measured length appears in JSON and the local SVG review. Optional dimensions come from a selected saved project netclass, without assumed impedance targets.

- **Copper Balancer:** floating copper thieving, shape/layout presets, layer scope and density review; a dedicated native KiCad launcher keeps polygon operations out of the incomplete IPC facade and writes an explicit board copy.
- **Mechanical Check:** component/enclosure solid interference, height and assembly checks with local 3D inspection and offline evidence reports; dedicated KiCad/FreeCAD runtime discovery.
- **Visual Diff:** Git revision and working-tree comparison using native KiCad SVG exports, an offline review page and a compact local launcher. Optional GitHub service functionality is never started by the plugin.
- **BOM Studio:** native KiCad fields, columns, grouping and export-format configuration; persistent workspace settings; variant and catalogue tools; CLI configuration; library-root precedence fixes and local server lifecycle checks.
- **Embed3D:** portable project and model workflows; saved-file IPC operation boundaries; fixes for KiCad 10 UTF8 library identifiers, parsed-object ownership corruption and backside footprint normalization. Unsupported live IPC library operations are visibly disabled.
- **Manufacturing Readiness:** verification bound to saved input bytes, profile, jobset and live board state; CLI checks run on private copies; hashed output archives are published atomically.

## Installation and automation

Install individual `WayriCAD-*-3.0.0-PCM.zip` files through KiCad PCM's Install from File command. Each package includes its runtime, local help and light/dark toolbar icons. The source installer previews destinations and backs up existing plugin installations before replacing them.

The CLI provides document automation, routing plan/apply commands, SVG review files and settings discovery from a board. BOM Studio and Embed3D retain their application CLIs. See the [CLI guide](CLI_USER_GUIDE.md) and [installation instructions](../README.md).

## Compatibility and verification

This is a **testing release**, not a KiCad 11 certification. The packages use official IPC plugin manifests and require KiCad 10 or newer. Native geometry/file tests were run with KiCad 10.0.5. The headless routing file CLI still needs KiCad 10's SWIG Python interpreter. Dependency provisioning can require network access on first installation; the application interfaces and project processing are local.

The [validation record](audits/VALIDATION_3.0.0.md) lists checks and results. The [compatibility report](COMPATIBILITY.md) separates native tests, SDK contract tests, live transport evidence and remaining host limitations. Full production-board DRC, every tool's end-to-end IPC workflow, future KiCad 11 behavior and every display/DPI combination have not been certified.

## Migration

Install the new package IDs and remove obsolete PCM entries to avoid duplicate toolbar actions. Preserve existing project/workspace data. The 3.0.0 release replaces the old published package assets; historical source notes remain in the repository as archival documentation.
