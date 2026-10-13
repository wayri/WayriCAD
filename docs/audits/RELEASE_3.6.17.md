# WayriCAD 3.6.17 release validation

This release packages readable selectors and connector-edge breakout from develop. Earlier published binaries remain immutable.

Feature evidence is recorded in [connector and dropdown validation](connector-edge-dropdowns.md): native Windows KiCad 10 geometry, Preview/Apply/Undo/Redo, local-rule export and DRC, the synthetic 78-pin connector, isolated package imports, and platform limits.

The release uses 17 IPC packages at 3.6.17 and the unchanged published Fusion 0.9.8 and Variant Manager 0.6.1 archives. Release source must pass the full CI matrix before publication. Package schemas/icons/entrypoints, documentation, wheel/source build and isolated wheel imports are checked locally. Uploaded artifacts are downloaded and compared to local SHA-256 values before feed promotion.

Skipped tests are not passes. Native GUI compatibility across every OS, DPI setting and KiCad version is not established. Independent connector escape is not complete routing or differential-pair qualification.

## Publication

Source commit `ddecfe91a8fcfd39beb6cc9fbf34da172e3158ba` passed all eight [CI jobs](https://github.com/wayri/WayriCAD/actions/runs/38478285540): Python 3.10/3.12/3.14 on Windows/Linux, Python 3.12 on macOS, and the PI known-answer benchmarks.

[v3.6.17](https://github.com/wayri/WayriCAD/releases/tag/v3.6.17) contains 23 assets: 19 PCM ZIPs, repository resources, wheel, source archive and SHA-256 manifest. All were downloaded after publication and matched local bytes. The 19 packages passed official schema, syntax, icons, entrypoints and checksum checks; eight affected archives passed isolated native imports. Source and packaged documentation and the isolated wheel CLI/report/service checks passed. Personal machine-path marker scans found no hits in the archive text payloads, wheel or source archive.

Fusion and Variant Manager preserve the prior published archive hashes and download URLs. PCM promotion follows public-asset verification, with LF-normalized feed JSON so descriptor hashes match served bytes.
