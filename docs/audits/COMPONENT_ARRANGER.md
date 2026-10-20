# Component Arranger 0.1.0 validation

2026-10-20, Windows, KiCad 10.0.6 and bundled Python 3.11. This is an independently installable source/candidate plugin; the public suite release and PCM feed are unchanged. An installed PCB Editor toolbar launch was not performed. Native windows, source operations and extracted PCM workflows were tested separately. Other operating systems and KiCad versions remain unverified.

## Behaviour and evidence

| Area | Implemented behaviour and checks |
|---|---|
| Scopes | Selected PCB footprints/groups, native PCB groups, schematic sheet paths, explicit checked references and saved-schematic wire clusters. Thirteen grouping tests cover drawn-wire path length, branches, unjoined crossings, repeated sheets, local/global label opt-in, alphabetical cluster names and malformed/missing sources. |
| Anchor and region | Inferred anchor, explicit confirmation, hard rectangular area centred on its original origin. Fixed/locked/contacted footprints retain their pose. Board outline, cutouts, other components and footprint keepouts constrain proposals. |
| Placement | Finite deterministic search over allowed positions, angles and sides using actual courtyard polygons and pad positions. Routing reservation uses native net-class and board minimum widths/clearances. Six-part tests cover broad spatial sampling with all eight 45-degree orientations and both sides, including a search-budget starvation regression. |
| Density and objective | Capacitor ordering first, projected different-net crossings second, requested density within five percentage points third, then pad/net MST length and capacitor distance. Outside the tolerance the nearest sampled density is preferred. Tests show different target densities produce different legal layouts. No global optimum, 90% reduction or routing-completion claim. |
| Capacitors | Explicit units, shorthand, normalized field aliases, declared EIA marking codes and Unicode micro units. Unknown/conflicting values remain unknown. Explicit targets must share the anchor-pad net. Strict ascending value-to-pad-distance ordering is tested. |
| Native transforms | Asymmetric pads and courtyard world coordinates checked at all eight 45-degree orientations on both sides. Bottom flips use measured native frames, retaining pad UUID, number and net. Native group membership/source serialization remain unchanged by extraction. |
| Apply boundary | Native DRC on detached saved-rule copies, zone refill, strict pad/via/zone connectivity partitions, pad/net identity and unchanged routing checks. New findings, group-involving findings, excessive baseline reports or rounded poses leaving the area block Apply. A native negative test rejects deliberately overlapping materialization. |
| Custody and recovery | Originating board identity, live native serialization, saved PCB/project/rule hashes and relevant live rule dimensions bind validation. Input controls and canvas anchor changes are blocked while planning. Live/saved rule mismatch, changed source/selection/context and altered proposals reject stale operations. Durable board backup, full native footprint snapshots (including field identities), exact in-window Apply/Undo/Redo, rotated-bottom restoration and injected post-mutation failure recovery are tested. |

## Checks actually run

- **55 plugin tests passed together in KiCad native Python** inside a normal wx event loop: 26 engine tests, 13 grouping tests and 16 native integration tests. Native integration includes real detached CLI DRC, bottom-side materialization, original 45-degree bottom placement restoration, live/saved rule staleness, changed saved files, JSON-safe native metadata, proposal tampering and exact rollback. A six-part power-net fixture verifies capacitor order with all eight rotations and both sides, passes native DRC, then restores exactly. A separate restoration-only regression covers custom fields, text angles, 3D metadata, roundrect/oblong-drill pads, selection, locks and group membership at all 16 angle/side combinations; its injected approval flag is not DRC evidence. Tests use disposable source projects.
- **466 shared tests and 176 subtests passed; 88 skipped**, in Python 3.14. Skips do not establish native compatibility. Registry, capability inventory, themed icon assets, help and package entry-point integration are included.
- The actual CLI validated and exported a new two-part candidate: baseline DRC zero, candidate zero, zero new findings, unchanged pad/net identity, native connectivity and routing. The original board stayed unchanged. Reusing an export basename was rejected.
- All **23 candidate PCM ZIPs** passed schema, independent runtime/action/icon and syntax checks. The extracted Component Arranger package passed native CLI validation/export, overwrite rejection and an actual native preview window with source-tree and sibling-plugin imports excluded. Its window closed through the normal event loop.
- Wheel build and isolated wheel CLI/import/assets checks passed. Documentation and local illustrations passed the source validator. No public release asset was replaced.

Native standalone runs can emit duplicate wx image-handler and SWIG ownership warnings while exiting successfully. These checks do not establish a leak-free long-running installed editor session or ordinary PCB Editor Undo integration.

## Examples and provenance

The native six-part screenshot is a synthetic fixture with two-pad parts, measured rectangular courtyards, two signal nets and explicit top/bottom permissions. The final preview reduces projected crossings **2 to 0** and pad/net MST length **71.85 to 17.49 mm**. This fixture does not validate bypass-loop electrical performance or typical dense-board routability.

`component_arranger_plugin/help-workflow.png` is a 1,344 by 861 opaque RGB native client capture. It shows actual controls, original/proposed geometry, highlighted area, side markers, metrics and the persistent action row. It contains no private paths, usernames or network identifiers; no redaction was needed. It is not a simulated marketing mockup.

The installed KiCad PIC Programmer demo's complete saved hierarchy was also analysed read-only through the actual CLI: **124 symbols, 21 wire clusters and five separately reviewable label links** at a 25 mm drawn-wire threshold. This proves saved grouping on that standard project; it is not a claim that its already-routed PCB was rearranged or requalified.

## Explicit limits

The planner supports up to 128 selected footprints and 512 selected plus relevant external pad endpoints. It does not omit endpoints to fit a limit. Search is bounded by pose attempts and passes; infeasible/incomplete results retain original poses and cannot enable Apply. Missing/malformed movable courtyards fail actionably. THT geometry reserves both sides and retains its original side; bottom SMD placement does not establish 3D collision clearance.

Locked/routed/contacted parts remain fixed. Existing native group graphics are not rearranged with footprints. The plugin neither moves attached copper nor routes missing connections. Projected net-MST crossings and length are proxies, distinct from native ratsnest completion, propagation delay and actual routed length. BGA/LGA/QFN/QFP advisories require separate pin-escape, via, return-path and assembly review.

Saved-wire grouping does not infer live selections from another Schematic Editor window. Parent-to-child hierarchical port mapping, bus membership and implicit power connections remain explicit limitations. Local/global label jumps require user opt-in. Group inference never changes schematic connectivity or source files.

Refill zones and run final native DRC after Apply. Undo belongs to the plugin window; saving or external edits can invalidate it, and closing the window discards its transaction object. Keep the saved backup and matching original project/rules when restoring manually. Release qualification across real dense-board families remains future evidence, not inferred from these synthetic fixtures.
