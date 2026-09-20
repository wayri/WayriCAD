# Development-folder integration — 2026-09-14

Imported three distinct applications from a user-provided external source directory, bringing the WayriCAD 3.0.0 testing suite to 22 independent PCM packages. Source directories were read only. Git internals, caches, large third-party examples, generated reports and old build products were excluded. Each imported directory records source provenance and retains available license notices.

| Source | Integrated package | Integration and verification |
| --- | --- | --- |
| CopperBalancer 0.2.0 | `copper_balancer_plugin` | Native KiCad 10 polygon engine, compact neutral preview, legacy generated-net recognition, explicit saved-board output-copy workflow and CLI. All 29 native tests passed; ordinary Python passes 14 and skips 15 native tests. Real UI review showed 1,174 proposed shapes with board copper and holes. Native CLI generated a new copy and preserved source bytes. |
| 3d-interference-check / 3Dvalid 0.1.0 | `mechanical_check_plugin` | Compact Board/Rules/Run/Review/Report navigation, stale-result invalidation, saved-file launcher, runtime diagnostics, CLI and offline reports. All 24 tests passed, including seven real KiCad 10.0.5 / FreeCAD solid-pipeline checks. Actual Board window captured and inspected; populated native viewer behavior exercised, but its OpenGL rendering was not visually certified. |
| nativegitvizdiffkicad 0.1.0 | Removed standalone Visual Diff | Compact local launcher and self-contained native SVG review page; atomic exports, safe Git snapshots, wheel resource loading and CLI. All 15 tests passed. KiCad 10.0.5 rendered PCB and schematic comparisons at two committed fixture revisions. Actual launcher captured and inspected; browser report visual QA remains unverified. |

Suite verification: 121 root tests passed, 12 runtime-dependent skips and 85 passing subtests. All 22 PCM ZIPs passed official schema, entrypoint, Python syntax, icon, payload and SHA-256 validation. The isolated wheel passed all three CLI help commands, Visual Diff report asset loading and Mechanical Check rules export without using checkout imports. Imported test suites are included in the Windows/Linux CI matrix; the previous six green CI jobs predate this addition and are not evidence for the new source revision.

New console commands: `wayricad-copper`, `wayricad-mechanical`, `wayricad-diff`. Their native engine requirements are documented individually; installing an IPC manifest does not establish live editor acceptance or KiCad 11 support. Copper and mechanical geometry still require native KiCad 10; Mechanical Check also needs FreeCAD. Visual Diff uses Git and `kicad-cli`. UI assets and reports are local. The optional imported GitHub service is not enabled or configured.

The standalone Visual Diff implementation was subsequently removed from the repository and its reachable history. Its commands and results above describe the historical integration only.

This record covers local verification. GitHub Actions records the separate Windows/Linux results for each pushed revision; release assets carry SHA-256 checksums for download verification.
