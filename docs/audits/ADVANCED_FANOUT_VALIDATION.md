# Advanced fanout validation

The implementation adds four styles, explicit angle references, naming-based interface presets, paired paths, netclass dimensions and multi-segment previews/CLI serialization.

- Native KiCad 10: **40 routing/CLI tests passed** (21 advanced, 17 existing, 2 SVG/settings). Coverage includes rotated footprints, board and footprint angle references, second-segment obstacles/edges, unrelated-layer tracks, existing same-net via overlap, pair completeness, spacing, skew, consistent transitions, atomic rejection, terminal via flare and explicit preset overrides.
- Ordinary Python suite: **126 passed**, 30 runtime-dependent skips, 85 passing subtests. Native cases above supply separate evidence for routing skips.
- Actual wx UI: segmented preview generated eight escapes and 16 trace segments; Preview left the source unchanged, and Apply/Undo/Redo handled 24 generated items.
- Paired wx UI: named SERDES mates produced equal measured lengths; table pair IDs/lengths and rendered segment/width counts matched the plan. Apply/Undo/Redo passed. Actual segmented and paired screenshots were captured and visually inspected.
- Stale review: editing saved `.kicad_pro` class dimensions or changing controls without emitting an event blocked Apply and placement review without board mutation.
- Native file CLI: a two-net paired plan exported all bends to JSON/SVG and applied four segments to a new board; tampering with a bend was rejected and source bytes were preserved. All 22 rebuilt PCM ZIPs passed schema/payload/icon/hash validation.

Profiles are editable geometric starting points, not protocol certification. Differential measurements cover generated breakout copper only. Full live IPC acceptance, future KiCad 11 and production-channel timing/impedance remain outside this verification. See [the feature guide](../ADVANCED_FANOUT.md).
