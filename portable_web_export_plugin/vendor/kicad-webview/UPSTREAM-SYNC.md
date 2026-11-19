# Extension synchronization: 0.5.0

The native read-only BOM/board analytics engine was ported from the main KiCad Online extension working tree, based at commit `ecb2ca40baf80981e36ad948b29c4166cb808ef2`. Its working tree included unpublished changes; this is a file snapshot, not a claim that all source matches that commit. Upstream `extension/bom-analytics.js` SHA-256: `ca80cba6bf46e8299ea878b37bfad28a9d414c98e43603a7672cb4f319e24059`. The library copy adds its MPL header; bounded public adapters and UI are maintained separately.

The renderer audit found the web library already ahead of the inspected extension in native 3D depth/clipping, translucent copper layers, registered WayriCAD fields, source selection and embed lifecycle. Those fixes are retained. Editor, comments, authentication, procurement and extension-only persistence are not imported.

Retained synthetic native Bezier references were copied from the extension tests. Their recorded KiCad CLI version is 10.0.6, exported 2026-11-03. This release checks the retained output; it does not claim a fresh native export. Tests cover bounded cubic flattening, mirrored/rotated transforms, pin/wire connectivity, malformed geometry warnings and agreement with retained SVG coordinates (PCB 0.00501 mm; schematic 0.006 mm). These are geometric checks, not universal font/pixel fidelity or all-version compatibility.

See [BOM semantics and limits](BOM-ANALYTICS.md), [mobile performance](MOBILE-PERFORMANCE.md) and [WayriCAD result limits](WAYRICAD-RESULTS.md). Existing draw/texture/offscreen budgets remain; no new physical-device benchmark is claimed.

## 0.6.0 completed-candidate refresh

The second sync uses the actual 0.12.94 release candidate working tree based at `4a6b9147f165cefa38eb83365aac8d7fdf14f5fe`. Feature work was complete while extension packaging continued. Exact upstream per-file hashes are retained in `SOURCE-PROVENANCE.json` under `extensionRefresh060`; selective library adaptations are tested separately.

Ports include native saved color/fill/dash and bounded text/image previews, terminal/flag connectivity, cap/wall depth precedence, reversible exploded inspection and right-pan selection protection. Library-native additions provide bounded camera memory, parallel listed-sheet loading and the reopenable sheet browser. [Behavior and limits](EXTENSION-REFRESH.md). No extension comments, browser-session authentication, variant editing or Fast PI solver/setup is imported. Saved BOM remains a saved-source summary; saved WayriCAD fields remain independently inspectable.

## 0.7 file-compatibility refresh

The 0.7 source selectively ports the extension text resolver, text context and bounded expression handling, plus horizontal schematic tables, local-label orientation and visible PCB custom properties. It retains the library's existing rendering and interaction work. This is a selective port, not a claim of complete extension parity or a new upstream commit identity. See [behavior and limits](EXTENSION-REFRESH.md). The full suite recorded 554 passing tests and builds passed; real-browser verification remains pending.
