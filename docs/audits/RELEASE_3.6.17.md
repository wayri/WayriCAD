# WayriCAD 3.6.17 release validation

This release packages readable selectors and connector-edge breakout from develop. Earlier published binaries remain immutable.

Feature evidence is recorded in [connector and dropdown validation](connector-edge-dropdowns.md): native Windows KiCad 10 geometry, Preview/Apply/Undo/Redo, local-rule export and DRC, the synthetic 78-pin connector, isolated package imports, and platform limits.

The release uses 17 IPC packages at 3.6.17 and the unchanged published Fusion 0.9.8 and Variant Manager 0.6.1 archives. Release source must pass the full CI matrix before publication. Package schemas/icons/entrypoints, documentation, wheel/source build and isolated wheel imports are checked locally. Uploaded artifacts are downloaded and compared to local SHA-256 values before feed promotion.

Skipped tests are not passes. Native GUI compatibility across every OS, DPI setting and KiCad version is not established. Independent connector escape is not complete routing or differential-pair qualification.
