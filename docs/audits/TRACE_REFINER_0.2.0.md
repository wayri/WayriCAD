# Trace Refiner 0.2.0 validation

## Environment and scope

2026-10-20: Windows, KiCad 10.0.6, bundled native Python 3.11; shared tests use Python 3.14. This is the independent plugin 0.2.0 source/candidate, not a new suite release. The published PCM feed remains unchanged. Native source and extracted-installer windows were exercised; launching an installed toolbar action inside PCB Editor was not performed. Linux/macOS and KiCad 11 remain unverified.

## Improvements

| Area | Change and acceptance evidence |
|---|---|
| Fragmented routes | Up to 2,048 segments per eligible chain; exact collinear preprocessing, bounded local search and intersection pruning. A 402-segment native fixture passes detached DRC/connectivity validation and exact Undo. Over-limit chains are preserved as a unit. |
| Geometry bounds | Full bidirectional path coverage, native-coordinate recheck and one shortening budget per chain remain mandatory. Rotated/translated fixtures, independent dense-distance comparisons, fragmented tuning and invalid/self-intersecting cases supplement the conservative production proof. |
| Native contacts | Spatial indexes narrow net/layer/bounding-box queries before native shape tests. Exact unchanged collinear copper may collapse at interior contacts. Jog changes retain conservative contact checks. |
| Property boundaries | Width, layer, net and local soldermask differences split chains. Groups, locked objects, arcs, differential/timing constraints and tuning remain protected. Via-connected front/back fixtures preserve the via and bottom routing. |
| Review | Before/after length, shortening and segment metrics; click-to-focus preview; tooltips; multiple proposal exclusions. Exclusions discard approval/evidence and require independent validation of the retained subset. |
| Staleness and writes | In-memory native board fingerprints; originating native-board identity and a digest binding validation to proposal/settings. Modified proposals/replacement objects are rejected. Add/Remove failures after mutation and later snapshot failures restore source membership or report recovery requiring inspection. |
| Performance | Exact-collinear preprocessing, bounded 1,024-window search, native contact indexes and batched transaction membership checks remove avoidable repeated work. No whole-suite or cross-machine speedup claim is made. |

The geometry planner retains its 30-second overall budget. Search limits can leave possible improvements undiscovered. Displacement and shortening are in millimetres; defaults remain 0.10 mm each. No added-length allowance, timing qualification or impedance acceptance was introduced.

## Automated and native checks

- **58 plugin tests passed** in 100.984 seconds with normal wx event-loop shutdown. This includes geometry, scopes, contacts/topology, real native DRC rejection/approval, via-connected layers, protected routing, native groups, mask boundaries, stale previews, tampering, transaction failures, cached viewport and review/exclusion workflows.
- **466 shared tests and 173 subtests passed; 88 skipped** in 22.57 seconds. Skips are not native compatibility evidence. The initial run hit a Windows host stdin `DuplicateHandle` error in an unrelated RLC subprocess test; rerunning with a valid null stdin handle passed without source changes.
- All **22 candidate PCM ZIPs** passed package/schema/action/icon/syntax checks. The extracted Trace Refiner ZIP passed actual native preview, detached worker DRC, Apply/Undo/Redo and native window construction/closure without source-tree or sibling-plugin imports.
- Wheel build and isolated wheel imports/CLI/assets smoke checks passed. Native standalone capture/isolation processes emitted duplicate image-handler and SWIG unowned-track cleanup warnings; they exited successfully. These checks do not establish a leak-free long-running installed editor session.

## Standard KiCad boards

Copies of the unmodified demos distributed with KiCad 10.0.6 were used. Outputs were written to new files; source files were retained. Default 0.10 mm bounds and protected-net patterns were used.

| Board | Source PCB SHA-256 | Result |
|---|---|---|
| ECC83 push-pull amplifier | `6bf836ce6524056c40581cfebe36951f1637bedfbd53c7f47f6bc85b6856d5c4` | Preview: zero proposals, one preservation notice. No refined result claimed. |
| PIC Programmer | `aba03b4359e8bf162fe00b27b0d3394f2141acfbd3d43d9cf8e05bf0845d9bd5` | Five changes validated and exported through the actual CLI. Native DRC baseline 13, candidate 13, zero new findings; native terminal connectivity unchanged. Existing findings are not represented as a clean-board pass. |

The [KiCad demo sources](https://gitlab.com/kicad/code/kicad/-/tree/10.0/demos) provide representative routing, not a fabrication certification standard or exhaustive router benchmark.

## Marble scale check

The saved [public Marble revision](https://github.com/BerkeleyLab/Marble/tree/a426777d92c0f22a546d4740b419a3937e0c1f90/design) has 41,044 routed items. The final read-only CLI preview generated **283 proposals and 260 preservation notices**. Notices do not count all scope/protection exclusions. The tested PCB SHA-256 is `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.

Marble application remains blocked by the excessive existing DRC baseline documented in the [earlier audit](TRACE_REFINER.md). No new Marble native DRC run or validated Marble edits are claimed here. Equal aggregate DRC totals cannot bypass the 199-per-type baseline gate.

## Screenshot provenance and limits

`trace_refiner_plugin/help-review.png` is a native 1,920 by 1,032 window capture of a disposable synthetic fixture: SIGNAL changes from five to one segments, 6.0249 to 6.0000 mm. It shows focus and exclusion controls, not a public-board result. No private source paths or machine identifiers are visible; no redaction was needed. The earlier workflow screenshot is retained.

Trace Refiner remains bounded geometric cleanup, not an obstacle-shove router or automatic differential-pair/timing optimizer. Refill zones and run final native DRC after applying changes. Review the actual fabrication and signal requirements before saving.
