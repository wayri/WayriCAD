# Silkscreen Label Placer 0.2.2 — adaptive and net labels

20 October 2026. Native checks used Windows and KiCad 10.0.6 bundled Python 3.11,
wxPython, and kicad-cli. The 0.2.1 courtyard and glyph-envelope checks remain.

## Behavior

Each label tries nearby common-direction sizes first, then nearby 45-degree
increments, then other enabled angles. Only afterward does it try distant guide
placements. Default fine angles use 15-degree increments; arbitrary explicit
angles in [0, 180) are accepted, up to 36 total. Both board faces and reading
reversal are supported. Staggered footprint-edge slots and bounded obstacle-edge
slots complement the clearance-scale grid. Search distance is measured from the
footprint envelope, including large parts.

Nearby accepted positions and complete guide strokes retain strict courtyard,
pad/mask, silk and board-boundary checks. Guides try direct, diagonal/L-shaped
and two-bend paths before a mixed-angle visibility graph. The fallback has at most
48 nodes and 2,048 checked edges; every native full stroke must pass the same
clearance/outline callback. A three-wall maze exercises eight route vertices at
these production budgets. No unchecked segments are accepted on exhaustion.

The common direction has up to 768 nearby/4,096 distant candidates per size;
other angles have 128 nearby/512 distant candidates. Each label is capped at
12,000 candidates and receives a fair share of the 30-second plan budget.
Native obstacle edges find narrow off-grid slots without exhaustive raster
search. Work/time caps can still leave feasible arrangements unresolved.

Options → Placement adds an opt-in net-name mode and reference wildcard (`TP*`
by default). A matching test point with exactly one assigned, nonempty net gets
a separate managed silkscreen annotation. The real component reference/value,
UUID and pad connectivity remain unchanged. Only the reference's display is
suppressed. Full hierarchical names are used without truncation. Missing or
ambiguous nets and unsupported control/text-variable syntax are reported rather
than guessed or silently expanded. Hidden/locked items and selection scope stay
protected.

Ownership is recorded against footprint/reference UUIDs in a versioned group;
invalid ownership refuses modification. Repeat previews update the owned text
rather than creating duplicates. Disabling the option restores reference display
through the checked layout planner and removes only the owned annotation. Undo,
Redo and failure recovery include text, visibility, board presence and group
membership. Save/load preserves ownership. Net names are reviewed snapshots:
rerun Preview/Apply after connectivity or component-position changes.

## Evidence

| Native check | Result |
|---|---|
| 100-part explicit-courtyard fixture | 100 accepted; independent native DRC zero violations and zero unconnected items |
| Public Marble snapshot, 1,006 footprints | 182 eligible, 83 accepted and 99 unresolved in 15.969 seconds; unchanged source SHA; all accepted native envelopes clear |
| Marble independent DRC | 481 before, 476 after; zero new violation type/item-UUID keys; existing violations remain |
| 18-part explicit-courtyard fixture | All 18 accepted; different labels used 1.0 and 0.8 mm; Undo restored the exact fingerprint |
| 8 mm blocked part | Label placed within an 8 mm search radius; guide segments clear the pad/stroke margin; reversible |
| Four-test-point board | Four full net names and four guides accepted, no unresolved labels |
| Independent kicad-cli DRC on net-name fixture | Zero violations, zero unconnected items |
| Reference identity | TP references/values, footprint UUIDs, pad net names and pad positions unchanged |
| Net annotation lifecycle | Read-only Preview, idempotence, update, disable, Undo/Redo and save/reopen checked |
| Failure cases | Missing/ambiguous nets, hidden/locked/unselected parts, variable syntax, post-mutation add/visibility/removal failures checked |
| Options UI | Checkbox and pattern fit; enabled `TP*` settings round-trip and reopening existing annotations checked |
| Final native suite | 72 tests passed, real wx event loop and normal process exit |
| Angle and search priority | Native 0/17/45/90/135-degree placement on both sides; common direction beats existing rotation; nearby smaller horizontal text beats distant larger text |
| Large footprint | A 26 mm part receives an outside label and clear guide despite its label centre lying beyond the old origin-based radius; exact Undo |
| Multi-bend routing | Deterministic eight-vertex maze route at production node/check caps; blocked paths, bounded work, arbitrary/diagonal segments and callback failures tested |
| Root regressions | 466 passed, 88 skipped, 170 subtests passed; skipped native contexts are not passes |
| Multi-label recovery | Canonical current-property fingerprints preserve exact Undo despite native container reordering; actual property edits still invalidate |
| Isolated PCM | Saved four-TP annotations, disable, repeated exact Undo/Redo and native UI reopening passed without sibling/source imports |

`help-net-labels.png` is a 1200×800 raster from the actual native preview drawing
method, using a disposable four-test-point board. It is not a desktop capture,
contains no personal paths, and shows the reviewed glyphs rather than enlarged
screen text. Earlier preview assets remain in the source.

Unresolved and unrelated original silk can still have existing board violations.
Native Linux/macOS GUI and KiCad 11 remain unverified. This feature labels an
assigned net; it does not prove copper routing continuity or replace native DRC.

These counts are a bounded-search snapshot, not an optimal-coverage claim. The
new direction-first policy and per-label time sharing change placement choices;
Marble coverage is lower than the older 0.2.1 search. Per-label time limits mean
coverage can vary with machine load. Unresolved labels retain their original
geometry and may account for existing violations.
