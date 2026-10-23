# WayriCAD 3.6.29 release validation

This release packages changes through `bf27b6b5`, plus release metadata and
documentation. Prior functional evidence is recorded in the
[Constraint Studio audit](CONSTRAINT_NATIVE_OVERLAP_2026-10-23.md),
[Fanout trials](FANOUT_REAL_BOARD_TRIALS_2026-10-23.md) and
[native screenshot audit](ROUTING_README_SCREENSHOTS_2026-10-23.md).

The candidate must pass exact-source CI, package/document checks, isolated wheel
imports and affected extracted-PCM workflows before publication. Public feed
descriptors remain on 3.6.28 until the new assets are published and their public
downloads match local SHA-256 hashes. No published asset is replaced.

All 18 IPC packages advance to 3.6.29. The six native packages receive independent
patch bumps to include the updated guides and screenshots without reusing old
package versions. Their functional source is unchanged apart from version
identifiers. The suite contains 24 independent PCM ZIPs.

Native source checks used Windows, KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2.
Full dense-board BGA/residual connector fanout remains unvalidated; the release
does not turn rejected or timed-out plans into successful routing. The Studio
fixture's native DRC reported violations, not a clean design.
