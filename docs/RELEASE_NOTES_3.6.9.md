# WayriCAD 3.6.9

Project Fusion 0.9.7 adds a guided import flow and explicit variant destinations.
Choose a new or working project, select the detected source/sheet scope, choose
the source configuration and continue to settings, preview and Create / Apply.
Secondary source actions appear under Show advanced source actions. Native
windows use Fusion's bundled icon; the guide includes captured example windows.

Each source configuration can become the imported base, merge into a working
native variant, or remain a separate named variant. Named modes preserve source
Default and attach overrides only to rebased imported instances. Existing target
configurations stay unchanged. Whole projects and selected sheet occurrences
are supported. New-project sources can share a destination name by creating it
with Separate and choosing Merge on the other sources.

Fusion's CLI covers discovery, new projects, imports, linked updates and recovery,
sections, repair copies, fields/BOM and dependencies. JSON previews can be saved
and applied later. Existing-project writes require `--apply --yes --editors-closed`;
source hashes, native checks, verified backups and rollback remain active.

Native validation used Windows and KiCad 10.0.6: named new-project/existing-project
imports, selected-sheet import, real BOM exports, source preservation, offline
CLI apply with a verified backup, guided navigation and window icons. Shared
tests and portable Fusion regressions were also run; opt-in skips are recorded
in the [validation audit](audits/2026-10-08-fusion-variant-flow.md).

Named footprint substitutions are refused; named PCB-presence changes require
schematic-only import. Automatic linked updates of named imported configurations
are blocked until they can retain both states safely. Base-state linked updates
remain available. Native geometry/connectivity validation uses retained Default;
the selected named value/assembly state is reported separately. GUI drawing exports
and low-level live IPC adapter operations are not CLI workflows. Linux/macOS
native-window qualification remains unverified.

Install Fusion 0.9.7 through PCM and restart PCB Editor. Other independently
installable plugins retain their existing published versions, including Variant
Manager 0.6.0. See the [Fusion guide](../project_fusion_plugin/README.md).
