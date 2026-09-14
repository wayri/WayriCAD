# WayriCAD repository audit — 2026-09-14

The suite needs a geometry and operation-lifecycle overhaul alongside its UI work. Its weakest workflows can display a plausible preview while accepting invalid geometry, ignoring a requested restriction, or losing track of partially completed mutations. Adding more controls to those workflows would compound the problem.

This is the **pre-migration baseline audit**. Subsequent implementation and validation are recorded in [the 3.0.0 release notes](../RELEASE_3.0.0.md) and [compatibility report](../COMPATIBILITY.md). Line references below refer to the original snapshot.

This audit covers the original 17-package inventory, the shared UI and automation infrastructure, and a deeper examination of fanout and via stitching. Other plugins received a source-level architecture/workflow review, not a complete correctness audit. No production implementation had been changed at the time of this baseline audit.

## Evidence and limits

- `python -m unittest discover -s tests -v`: 94 tests, 93 passed, one skipped because the ordinary Python environment lacks pcbnew; elapsed test time 10.094 seconds.
- Isolated probes with installed KiCad 10 Python reproduced the missing-zone bypass, global reference exclusion, invalid fanout dimensions, overlapping pattern algorithms, through-hole inclusion in SMD scope, incompatible selection signature, and absent geometry RPC methods.
- The probes call existing methods with lightweight control/selection substitutes and an in-memory native board. They do not instantiate plugin windows, open user board files, or add generated tracks/vias to a board.
- Reviewed the checked-in fanout/stitching `help-workflow.png` images. These are empty demo captures, not evidence of successful dense-board interaction or current live-editor rendering.
- Native-editor undo interaction, save/autosave during temporary previews, real-board DRC, high-DPI layouts, and performance on large boards remain unverified. Risks below that depend on those interactions are identified as source-level findings, not reproduced editor failures.

Reproduce the isolated checks from the repository root:

```powershell
& 'C:\Program Files\KiCad\10.0\bin\python.exe' docs/audits/geometry_probe.py
```

The probe prints observed behavior, including defects. It is an audit reproducer rather than a regression test that asserts correct behavior.

## Prioritized defects

P1 means geometry correctness, loss of recoverability, or an unreliable user-visible guarantee. P2 means a significant capability, interaction, or maintainability gap.

| Priority | Finding and concrete trigger | Evidence | Required correction |
|---|---|---|---|
| P1 | Stitching silently disables “Only inside target-net copper zone” if no matching zone exists. A 5 × 5 mm probe accepted 9 vias with the checkbox enabled and no zones. | `via_stitching_plugin/via_stitching_plugin.py:334`; reproduced. | Require matching usable copper when requested. Report missing/unfilled geometry explicitly and prevent generation until resolved. |
| P1 | “Skip refs” can reject the entire candidate set: if any footprint has a listed reference, `_blocked_reason` returns `footprint` regardless of candidate position. The far-away probe reproduced this. | `via_stitching_plugin/via_stitching_plugin.py:261`; the reference test and containment test are joined by `or`. | Define whether this control excludes placement around named footprints or exempts them from exclusions; apply its spatial test accordingly and rename it clearly. |
| P1 | Stitching obstacle tests examine candidate centers, without inflating for via radius or required clearance. Existing same-net vias are ignored, so repeat runs can propose duplicate/overlapping vias. | `_blocked_reason` at line 261 and `_plan` at line 317; source-level. | Evaluate the complete via copper/drill geometry against layer-aware obstacles and board/netclass requirements; reject duplicates and collisions among new candidates too. |
| P1 | “Full board bounds” is only an axis-aligned Edge.Cuts bounding rectangle. Concavities, cutouts, and true edge distance are not tested by the planner. | `_bounds` at line 311 and `_plan`; source-level. | Use actual board polygons, holes, and geometry offsets. This matters especially when target-zone restriction is disabled or bypassed. |
| P1 | The keepout/drawing checkbox only inspects `GetDrawings()`. The planner does not interpret rule-area via restrictions or validate the via across its intended layer span. Filled-area API failure falls back to generic hit testing. | `_inside_zone` at line 252 and `_blocked_reason`; source-level. | Handle rule areas explicitly, validate relevant layers, and report unsupported geometry instead of silently weakening the check. |
| P1 | Fanout's SMD scope includes through-hole pads: it accepts both `PAD_ATTRIB_SMD` and literal `0`; installed KiCad defines PTH as `0` and SMD as `1`. | `fanout_generator_plugin/fanout_generator_plugin.py:224`; reproduced with a PTH pad. | Compare to the actual SMD enum; do not use a guessed fallback that admits another pad type. |
| P1 | Fanout accepts physically invalid dimensions. The probe produced a plan with −0.2 mm width, −1.5 mm length, and 0.6 mm drill inside a 0.3 mm via. Stitching validates positive spacing but lacks equivalent complete dimension checks. | Fanout `_plan` at line 254; stitching `_plan` at line 317. Fanout reproduced. | Validate finite positive dimensions, drill/diameter relationship, annular ring, clearances, bounds, and supported layers before creating any board objects. |
| P1 | Fanout has no route-obstacle/candidate-collision checks. Choosing an escape layer different from the SMD pad's layer places the entire escape track on that other layer, without constructing a connected layer transition at the pad. | Fanout `_layer` at line 189 and `show_on_pcb` at line 318; source-level. | Route the initial segment on the pad copper layer; model the via transition and any continuation explicitly. Check connectivity and collisions before marking a candidate acceptable. |
| P1 | Commit clears `preview_items` before group creation succeeds. If group creation or membership assignment fails, the recovery list is already gone. Removal and undo/redo failures are swallowed while operation history advances and status reports success. | Fanout `generate`/`undo`/`redo` at lines 407/426/456; stitching at 475/494/524; source-level fault paths. | Retain ownership until successful commit, roll back partial writes, retain unresolved items on cleanup failure, and report partial outcomes accurately. |
| P1 | Modeless previews lack a board-revision guard. Fanout stores live pad references plus previously calculated endpoints; moving a pad without changing its selected identity can leave a mixed old/new plan. Commit only checks that temporary items exist. | Fanout `FanoutPlan`, `show_on_pcb`, `_selection_signature` at line 480; both `generate` methods. | Snapshot immutable geometry and relevant board state; invalidate on board/source changes and revalidate immediately before apply. |
| P1 | PCB preview inserts ordinary tracks/vias into the actual board. “Commit” primarily groups objects already inserted. There is no demonstrated isolation from editor save/autosave, native undo, or deletion while the modeless window remains open. | Both `show_on_pcb`, `clear_pcb_preview`, and `generate` implementations; source-level lifecycle risk. | Prefer a non-mutating editor overlay where supported. Otherwise explicitly model and test temporary ownership, save behavior, cleanup, and native undo interactions. |
| P1 | The richer preview helper calls `SetSelected(True)`, but installed KiCad 10 requires `SetSelected()`; its broad exception handler hides the failure. | `preview_kit.py:pcb_select_items` in shared copies; native signature mismatch reproduced. | Reuse the existing compatible `selection_utils` approach through a tested adapter; do not wire the richer canvas into more tools without fixing this. |
| P1 | Manufacturing release gates can become stale. Audit results and DRC/jobset booleans are retained without binding them to current source hashes/profile/jobset. DRC runs on the saved board path while the metrics audit reads the live board. | `manufacturing_readiness_plugin/manufacturing_readiness_plugin.py:79` and `:96`–`:105`; source-level. | Bind all checks and release contents to one explicit saved snapshot; invalidate gates when inputs or settings change. |
| P1 | Bulk label apply recomputes replacement text from current controls instead of applying the exact reviewed new values. Text edits need not create a fresh preview. A setter failure midway can leave earlier edits without recorded undo history. | `bulk_label_editor_plugin/bulk_label_editor_plugin.py:185` and `:207`; source-level. | Store immutable old/new edits, invalidate stale previews, verify old values, and apply transactionally. |
| P2 | Fanout and stitching have no executable CLI/RPC plan, preview, or apply handlers. The registry inventories these plugin actions, but its separate `operations` list contains no geometry operations. | `extract_pins_plugin/automation.py:20`, `:40`, `:233`; `fanout-generator.plan` and `via-stitching.plan` both return −32601 in probes. | Expose actual supported operations with input/output schemas and runtime requirements. Distinguish GUI-only actions from headless methods. |
| P2 | Dense stitching generation runs nested candidate loops and repeated full-board obstacle scans directly in UI handlers, without candidate limits, progress, or cancellation. | Stitching `_plan`, `preview`, and selection timer; source-level. | Preflight candidate count, build spatial indexes, run computation on immutable snapshots with cancellation, and discard stale results. Keep native board access on its supported thread. |
| P2 | Manufacturing subprocess execution blocks its event handler for up to 300 seconds. | `manufacturing_readiness_plugin/manufacturing_readiness_plugin.py:92`; source-level. | Use a cancellable process job with progress/log streaming and explicit failure/timeout state. |

## Fanout capability gaps

There are already ten named choices. The problem is their depth and controllability:

- Dogbone outward uses the same angle as radial outward; dogbone mainly forces an endpoint via. The probe returned 63.434949° for both at the same pad.
- BGA/LGA grid outward and perimeter outward use the same board-axis direction calculation; the probe returned 90° for both. There is no row/pitch/channel-aware BGA escape algorithm.
- Quadrants use board-axis signs; four-corner uses the footprint bounding box. These are not footprint-local, rotation-aware routing strategies.
- Each ordinary escape is one straight segment of uniform length. There are no adjustable bends, via offsets, row-dependent staggering, channel routing, or per-pad overrides.
- Layer choices are only Pad layer, F.Cu, and B.Cu. Via type and layer span are not configurable.
- Existing connected tracks, deliberately skipped/no-net pads, and previously generated escapes have no clear policy or diagnostic model. Via-in-pad on a no-net pad can produce a plan entry with neither track nor via.

Implement controls in this order:

1. **Scope and eligibility:** selected pads/footprints, reference/net/pad filters, connected/unconnected policy, no-net handling, locked-item policy, explicit selected count.
2. **Local geometry:** rotation-aware direction, 45°/90° escape, angle override, first-segment length, bend location, via X/Y offset, track width, per-side/per-row rules, and mirrored bottom-side behavior.
3. **Distinct strategies:** dogbone, staggered BGA dogbone, perimeter escape, row/channel BGA escape, radial escape, and via-in-pad. Each needs its own geometry definition and fixture-based expected output.
4. **Layer transitions:** supported copper layers from the board, via type/span, dimensions and manufacturing constraints. Enable only combinations supported by the chosen board/runtime.
5. **Editing and reuse:** pick a pad/candidate, suppress or override it, save a versioned preset, reopen a generated group with its original parameters, and preview a replacement before applying it.

A strategy should not be advertised as complete until rotation, bottom-side placement, fine pitch, center pads, multi-pad numbers, adjacent obstacles, and repeat application are covered.

## Stitching capability gaps

Current density options are variations on a rectangular grid. “Dense selected area” halves the step; “Dense perimeter / sparse interior” sparsifies the interior of a rectangular bounding box.

Needed controls and behaviors:

- Square and staggered/hex grids with independent X/Y pitch, rotation, and origin/phase.
- Explicit target polygon/zone selection, board outline and cutouts, drawn inclusion/exclusion regions, and clearly defined selection-bound behavior.
- True board-edge and zone-perimeter fences with offset, pitch, corner treatment, and optional multiple rows.
- Selected-track via fences with side selection, offset, spacing, and a defined treatment of bends and transitions.
- Via type/span, drill, diameter, annular ring, copper/edge clearance, and existing-via separation.
- Local suppression/addition and a density estimate before generation; per-candidate rejection reasons with coordinates and obstacle identity.
- Deterministic repeat application: preserve, replace, or extend an identified generated group without stacking duplicate vias.

## Preview and interaction redesign

Both geometry tools import `geometry_preview.py`, not their shipped `preview_kit.py`. The current canvas only binds paint and resize events. It renders tracks with a fixed 3-pixel pen, pads as fixed 6-pixel-radius circles, and vias as diameter-based circles with a minimum display radius. It omits pad shapes/orientation, drill holes, nearby copper, zones, keepouts, clearance envelopes, labels, and candidate diagnostics. Consequently it cannot support a credible clearance review.

The canvas is given zero growth proportion and a 190-pixel minimum height, while the result table receives remaining vertical space. The checked-in captures also show excessive blank space above the workspace, a small preview, and seven competing footer buttons. Actual small-screen/high-DPI behavior still needs live testing.

Proposed workspace:

- **Compact top context:** board, scope, selected count, active preset, dirty/stale state, and one sentence explaining the next action.
- **Scrollable settings sidebar:** scope, pattern, dimensions, layers, and exclusions with units, inline validation, contextual enablement, reset, and presets.
- **Dominant resizable canvas:** accurate board-coordinate geometry, cursor-centered zoom, drag pan, Fit board/Fit selection/Fit generated, layer toggles, scale, measurement, and selectable objects.
- **Collapsible results inspector:** accepted/rejected/overridden candidates, searchable net/pad/reference fields, sortable numeric values, reason details, and synchronized canvas/PCB selection.
- **Stable action area:** preview/update and apply as state-dependent primary actions; operation history and export as secondary actions. Retain distinct preview/apply semantics while simplifying the presentation.

Required behavior:

- Field changes update a debounced preview without destroying user pan/zoom or silently replacing a manually chosen scope.
- Selecting a row highlights its object without triggering a scope-changing regeneration loop.
- Accepted, rejected, suppressed, and unvalidated candidates have distinct symbols as well as colors.
- A rejected candidate remains inspectable rather than disappearing into an aggregate counter.
- Theme, DPI, keyboard navigation, focus order, panel sizing, empty state, busy state, failure state, and cleanup failure are designed and checked explicitly.

## Suite coverage and reusable foundations

| Package | Foundation present | Improvement focus from this scan |
|---|---|---|
| Extract Pins | Core parsing/tracing modules, substantial CLI, modeless board UI, several diagram workflows | Simplify navigation and repeated dialog/UI layers; preserve tracing tests and explicit ambiguity handling. |
| Bulk Label Editor | Preview table and window-local undo/redo | Exact reviewed edit plans, stale detection, atomic apply, inline validation. |
| Fanout Generator | Ten named patterns, modeless scope following, grouped operations | Geometry correctness, distinct algorithms, editable characteristics, rich preview, real headless backend. |
| Via Stitching | Grid/density controls, target-zone option, rejection counts | Fix bypass/exclusion defects, polygon/clearance checks, pattern types, editable preview, real headless backend. |
| Test Point Descriptor | Extraction/export and fixture support | Consistent selection/diagnostics and clear separation of documentation from PCB-writing operations. |
| Trace RLC / Impedance | Measurement/stackup modules, tabs, richer preview support | Reliable cross-selection and explicit input provenance; runtime coverage for board geometry adapters. |
| Signal Integrity Advisor | Separate analysis and measurement modules; I2C RPC | Broaden explicit automation coverage; validate shared selection behavior and consistent diagnostics. |
| Kilo | Separate CLI, operations, dependency modules, transactional file writes | Useful architectural reference; integrate discovery without duplicating its transaction logic. |
| Portable Assets | Separate engine, source checks, backup/lock safeguards | Preserve safeguards while unifying progress, recovery presentation, and capability discovery. |
| Variant Workbench | File hashes and guarded planning/application | Separate the large combined manager/UI module incrementally; maintain semantic variant protections. |
| Return-Path Auditor | Analysis backend, findings, pan/zoom scene, RPC | Correct shared selection adapter; clearly expose evidence and scope of geometric findings. |
| Harness Workbench | Analysis/report modules, interactive exports, RPC | Reduce task/navigation load and centralize validation across editor, exports, and automation. |
| Manufacturing Readiness | Fabricator profiles, DRC/jobset execution, release manifest | Snapshot-bound release gates and responsive cancellable jobs. |
| PDN Planner | Analysis backend, scene view, RPC | Correct shared selection adapter and retain traceable input assumptions in findings. |
| Protocol Constraint Composer | Separate rule analysis, editable presets, managed-rule backup/write | Consistent stale-source checks, error recovery, and machine-readable preview/apply contract. |
| Heater Designer | Separate analysis engine, thermal preview, generated groups | Review the same temporary geometry/undo lifecycle before expanding synthesis controls. |
| Planar Magnetics | Separate analysis engine, motion/field views, generated groups | Review temporary geometry/undo lifecycle; improve settings/result cohesion and reproducible presets. |

This is not a uniformly empty or unusable suite. Several tools already have useful backend separation, exports, and guarded file transactions. Preserve those investments while bringing geometry writers to the same standard.

## Architecture and CLI contract

Fanout/stitching planning currently lives in wx frame methods and reads controls directly. Stitching constructs native via objects during planning. This coupling prevents simple headless use and makes planner correctness difficult to test independently.

Introduce these boundaries:

1. Versioned settings and immutable board snapshots with stable item IDs, units, layers, nets, polygons, and obstacles.
2. Pure planners returning geometry plus accepted/rejected candidates, diagnostics, counts, and provenance. No wx controls or live pcbnew objects in the plan.
3. A board adapter handling snapshot collection, native API compatibility, revision checks, transactional insertion/removal, and recovery.
4. One preview scene model consumed by the GUI and file exporters.
5. GUI and CLI clients calling the same planner/validator; neither should implement a second geometry algorithm.

Proposed headless commands, not existing functionality:

```text
wayricad fanout plan --board input.kicad_pcb --config fanout.json --output plan.json
wayricad fanout preview --plan plan.json --output preview.svg
wayricad fanout apply --board input.kicad_pcb --plan plan.json --output output.kicad_pcb
wayricad stitch plan --board input.kicad_pcb --config stitch.json --output plan.json
wayricad stitch preview --plan plan.json --output preview.svg
wayricad stitch apply --board input.kicad_pcb --plan plan.json --output output.kicad_pcb
```

Plan files should contain a schema version, source/settings hashes, generator version, units, stable source IDs, full geometry, and structured diagnostics. Apply must reject a stale source, validate the exact reviewed plan, and default to a separate output board. In-place operation should be explicit and backed up. Capability discovery should enumerate real methods, schemas, supported environments, and whether a method writes. GUI-only operations must be labeled accordingly.

PCM package isolation is intentional: `CONTRIBUTING.md` forbids sibling-package imports in independently installed ZIPs. Keep a canonical shared source in development and vendor/generate package-local helpers during packaging, with synchronization checks. Do not solve duplication by introducing runtime imports that require users to install unrelated plugins.

Tests currently enforce identical helper copies, which is useful for packaging consistency but does not establish helper correctness. The disconnected richer preview and incompatible selection call show why a behavior-tested canonical source is needed.

## Delivery order and acceptance gates

| Stage | Deliverable | Completion criteria |
|---|---|---|
| 1. Correctness and recovery | Repair confirmed bypasses, enum handling, dimensions, selection adapter, stale-plan checks, and partial-operation handling | Behavioral tests reproduce each defect before the fix; injected Add/Remove/group failures never report false success or discard unresolved ownership. |
| 2. Headless planning | Shared settings/snapshot/plan models, geometry validation, executable CLI/RPC and SVG preview | GUI and CLI produce equivalent deterministic plans; normal imports do not require wx; native operations declare their runtime; stale plans and unsupported requests fail clearly. |
| 3. Preview workspace | Resizable context-rich canvas, linked diagnostics, inline editing and presets | Real populated-board review at standard and high DPI; pan/zoom survives edits; candidate picking and rejection inspection work; no accidental scope changes. |
| 4. Geometry strategies | Rotation-aware fanout strategies, BGA staggering/channels, polygon grids, perimeter/track fences | Fixture boards cover orientation, cutouts, holes, dense obstacles, multilayer constraints, duplicates, and repeat application; DRC compares the generated result to its baseline. |
| 5. Suite consistency | Responsive jobs, shared operation state, snapshot-bound release gates, controlled helper vendoring | Install each affected PCM ZIP in isolation; verify native lifecycle, error recovery, exports, themes, and declared automation operations. |

Start with a complete fanout/stitching vertical slice: validated geometry, safe apply/recovery, usable preview, and CLI parity. Use it as the reference workflow before changing all 17 interfaces.

The present green suite is a baseline, not a release-readiness verdict. `tests/test_suite_ux.py:test_geometry_tools_enforce_preview_before_commit` mostly checks strings and code structure; screenshot checks verify assets and dimensions. Add meaningful geometry, lifecycle, failure-injection, and native integration coverage before relying on those gates for a redesigned UI.
