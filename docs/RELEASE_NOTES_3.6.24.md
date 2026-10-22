# WayriCAD 3.6.24

The 17 IPC packages advance to 3.6.24 and Silkscreen Label
Placer to 0.3.3. The suite has 23 independently installable plugins. Five
unchanged native packages retain their published versions and package bytes.

## Silkscreen Label Placer

- Preserve acceptable references by default; choose all eligible labels,
  problem-only correction or selection-only correction. Reference-only mode
  leaves values and manual text alone.
- Try footprint-axis and perpendicular placement near the owning courtyard,
  normally within 2 mm. Projected edge corridors, bounded width/height changes
  and local staggering precede distant alternatives.
- Repack a bounded neighbourhood when needed. Reserve candidate checks for both
  nearby and farther search so many local size/angle combinations cannot starve
  later alternatives. Every eligible reference receives an explicit outcome.
- Printed leaders are off by default. Optional leaders are straight, with count
  and length limits, and require a clear association to the intended component.
- Persist generated text/guide ownership. Audit generated objects and explicitly
  remove verified generated leaders while retaining labels, with reversible
  cleanup. Uncertain legacy artwork is report-only.
- Show separate native courtyard and 2D footprint-hull distances, plus association
  warnings. Export before/after top/bottom HTML previews through the read-only
  CLI. The optional, project-scoped MCP adapter exposes settings, preview and
  audit; it has no board-writing tools.
- Protect courtyard/body proxies, native glyph envelopes, mask openings, board
  cutouts and face-specific via tenting. Preserve underlying layout and
  electrical fields through stale-state checks, rollback and exact Undo.

Legacy strokes left after label moves and a separate custom callout-generation
step were distinct problems. The latter is not attributed to the released plugin
as proof that it generates callout mazes.

Readability requires review beyond DRC. Finite search can leave references
unresolved. Automatic net-name wrapping, repeated-circuit placement reuse,
per-pin multi-net connector annotation and separate user-defined protected
regions are not implemented. Official MCP SDK 2.3.0 stdio/native synthetic checks passed; live-editor MCP
operation was not tested.

See the [plugin guide](../silkscreen_label_plugin/README.md),
[reference-board study](audits/SILKSCREEN_REFERENCE_BOARD_STUDY.md) and
[release validation](audits/RELEASE_3.6.24.md).

## Package versions

The 17 IPC packages are 3.6.24. Silkscreen Label Placer is 0.3.3. Fusion remains
0.9.11, Variant Manager 0.6.4, Trace Refiner 0.2.3, Component Arranger 0.1.3 and
Layer Counter 0.1.3.

## Validation

Windows KiCad 10.0.6: 171 native Silkscreen tests passed. The shared source suite
passed 494 tests with 88 skipped and 227 subtests. Copied-board text-only testing
accepted 674 of 720 references, retaining 46 unresolved; explicitly enabling the
10 short-guide allowance accepted 677 and retained 43 unresolved. Independent
ink/association checks passed. Native DRC was 295 → 288 with no new violation
type/item combinations in either case. Unresolved originals are not approved;
R164 remains unresolved in the whole-board results. The original project was
never written. See the audit for exact scope and publication checks.
