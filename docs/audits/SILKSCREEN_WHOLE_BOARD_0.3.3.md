# Whole-board silkscreen placement — 0.3.3 candidate

This implementation was tested on Windows with KiCad 10.0.6,
Python 3.11.5 and wxPython 4.2.2. Publication and feed promotion follow the release gates. Private boards and per-reference reports are not shipped.

## Placement contract

- Attempt every eligible reference; report changed, checked unchanged,
  unresolved and preserved items separately. Hidden, locked and non-silkscreen
  references are preserved, not counted as successful placements.
- Prefer positions within 2 mm of the owning courtyard, measured from the
  rendered glyph envelope rather than the text anchor. Try permitted smaller
  sizes and staggered positions locally before farther alternatives.
- Centre labels in the corridor projected from a courtyard edge. Wide text may
  extend past the projected corner lines if centred and collision-free.
  `edge_margin` controls the permitted centre offset; it is not a clearance.
- Prefer the footprint axis then its perpendicular (or optionally the common
  horizontal direction), followed by 45-degree increments
  and finer enabled angles. Near projected corridors precede floating slots;
  farther candidates prioritize distance across enabled orientations.
- Require a straight, unobstructed association to the correct component, even
  when no leader is printed. Reserve associations against later text and lines.
  No multi-bend leader routing is used. Virtual associations may cross ordinary
  decorative silk artwork; printed leaders must clear that artwork as well.
- Keep manufacturing floors, pads, mask openings, complete guide strokes,
  courtyards, other text and the native board outline protected. Extra
  courtyard padding is independent of manufacturing silk clearance.
- Follow native per-face via tenting and layer span. Optional drilled-hole
  protection also reserves tented drills. Tenting assumes intact manufacture.
- Preserve Preview source hashes, rollback, stale-plan checks and exact Undo.

The [reference-board study](SILKSCREEN_REFERENCE_BOARD_STUDY.md) records
immutable public sources and the limits of copying human layout conventions.
A polished board with hidden references is not evidence that all references fit.

## Verification

The native regression suite covers courtyard, pad, board-edge and guide
clearances; adaptive sizes; complete outcomes and retries; protected manual
text; stale Apply/Undo; rollback; native controls; and glyph centring across
rotation, justification and mirrored input. The final consolidated candidate passed **170 native tests**, with none
skipped. Subsequent presentation-only checks passed **15 UI tests** and
**5 report tests**. The focused search/readability suite passed **13 tests**. The shared suite passed **494 tests**,
with **88 skipped** and **227 subtests passed**. Windows subprocess handle capture
failed one earlier RLC CLI test; the isolated test and full shared suite passed
with pytest output capture disabled. No product code or assertion was changed
for that environment failure.

A public synthetic 100-reference board was placed with 100 accepted labels,
zero unresolved labels and no guides. Its rendered preview was inspected.
This regular fixture does not establish closure on dense irregular boards.

The difficult copied snapshot contains 720 eligible references. All are
attempted. An earlier projected-edge run accepted 677 and retained
43 unresolved originals; all five previously highlighted references were
changed successfully. Native glyph/board/pad/courtyard checks found zero
accepted-label violations. Manual text was unchanged and Undo restored the
exact source fingerprint. A trial search-budget revision failed the existing dense-board idempotence
regression and was discarded. That discarded trial is not used. The earlier counts above do not establish
coverage under the changed defaults.

Independent polygon checks covered all 677 accepted reference glyphs and 44
printed straight guides with **zero physical-ink violations**. All 677 serialized
associations were independently checked with **zero crossings of another courtyard,
text, guide or association**, including board/cutout containment. Five virtual
associations cross ordinary decorative silk graphics; these are not printed
leaders. Native DRC decreased from **295 to 288** findings, with **zero new
violation type/item-UUID combinations**, and zero unconnected items both times.

The independently built Silkscreen PCM passed official metadata/native archive
checks. Its extracted package imported independently, placed a synthetic label,
restored exact Undo and opened the native references-only window at 850 px.
Source documentation links and illustrations passed validation.

Screenshot provenance: `silkscreen_label_plugin/help-edge-alignment.png` is the
actual `LabelPreview` canvas drawn at 1200 × 1000 pixels using the public
`dense_board` fixture (10 × 10 parts, 3.4 mm pitch) with 2.2 × 1.4 mm courtyards.
It contains no private project geometry, machine identifiers or paths. This is
a native plugin canvas render, not a screenshot of a connected PCB Editor.
The PNG is stored as opaque RGB; no geometry, labels or results were edited.

All writes targeted disposable board copies. The original project was never
saved. Results apply to captured snapshots; they do not establish the current
state of an original that may have been edited independently.

## Consolidated defaults and current checks

The latest feedback prioritizes preserving acceptable placements, footprint-axis
orientation, readable width/height bounds and text-only placement. Leaders now
default off, with a configurable count/length budget when explicitly enabled.
Neighbour count and displacement are bounded. Every accepted reference has a
straight checked association, whether or not a line is printed.

The final text-only copied-board run attempted all **720** eligible references:
**674 accepted, 46 unresolved**, with **317 changed** and **357 accepted unchanged**.
Every accepted reference's serialized direct association was independently
checked: **zero crossings** of other courtyards, text, retained guides or other
associations; no virtual-only decorative-art intersections. Independent native
polygon exports/Shapely checks covered all 674 accepted glyphs plus 250 retained
legacy guide strokes, with **zero physical-ink violations**. Those legacy strokes
are not newly generated or automatically adopted. Native DRC was **295 → 288**,
with **zero new type/item-UUID combinations** and zero unconnected items.

Manual text and protected layout were unchanged; exact Undo restored the source
fingerprint. The final full run took about 216 seconds including setup, native metric
capture and validation (planner statistic about 162 seconds). These are local
fixture measurements, not a performance guarantee. R164 remains unresolved under
the default text-only policy. A separate, explicitly enabled short-leader run accepted **677**, changed
**320**, and retained **43 unresolved**. It used all **10 permitted guides**.
Independent checks covered all 677 glyphs/associations and 262 retained/new guide
strokes with zero physical-ink violations or required association crossings.
Native DRC was again **295 → 288**, with zero new type/item pairs and zero
unconnected items. Manual-text preservation and exact Undo passed.

R164 remained unresolved in that whole-board run. A separate diagnostic verified
a legal direct short-leader/two-owner repair within the configured 2 mm neighbour
displacement, but the whole-board guide allowance was already used. This is not
reported as full-board resolution of R164. Results now explicitly identify
checked candidates rejected by guide count/length constraints.

Among accepted labels with native courtyards, the largest actual glyph-to-
courtyard gap was about **1.794 mm** in both runs. Eight accepted labels lacked
usable native courtyard geometry in each run; their courtyard gaps remain
unknown and their separate 2D proxy metrics are labelled accordingly.

Earlier trials identified local candidate starvation and missed neighbouring
owners. The retained implementation reserves checks per phase, includes adjacent
owners in bounded repacking, and probes for actual blockers rather than moving
all nearby labels. Unverified legacy-guide corridors remain protected against
unrelated associations while their graphics stay report-only for deletion.

Ownership records bind generated annotation/leader UUIDs to footprint UUIDs and
settings. Verified cleanup is explicit and reversible; legacy namespace-only
artwork is report-only. Exact native glyph-to-courtyard gaps are separate from
2D hull proxy distances. HTML previews cover both faces and mark native DRC as
NOT RUN; independent native DRC must be performed separately.

Attribution: stale legacy strokes after text moves and excessive guides from a
separate custom callout-generation step were distinct observations. The latter
is not evidence that the released plugin produced callout mazes.

## Release status

Local default-policy and short-leader checks are complete. Publication gates,
exact-source CI and public download verification are tracked in the
[release record](RELEASE_3.6.24.md). Unresolved references
are retained and explicitly unapproved. No all-reference closure or universal physical legibility is claimed.
Official MCP SDK 2.3.0 stdio handshake, tools/settings, native six-part synthetic
preview/audit and out-of-root rejection passed on Windows/Python 3.14 with an
unchanged saved-source hash; this does not qualify live-editor MCP operation. Automatic
wrapping, per-pin multi-net connector annotations, repeated-circuit placement
reuse and separately configured protected regions are still unsupported.
