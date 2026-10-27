# WayriCAD 3.6.36 release evidence

## Layer Counter correction

Previously the ordinary styles mirrored only B.Cu. The new default compares
each physical front-to-back layer number with the midpoint of the complete
enabled copper stack. Four-layer L3 is therefore mirrored, including when it
is the only selected layer. Sparse native IDs and selected-layer subsets do
not change the midpoint. This is an ordinal convention, not a calculation of
the dielectric stack's geometric centre or actual core/prepreg construction.

Explicit `bottom-only`, `core-faces` and `none` policies remain available.
Core-pair position styles no longer force an alternating text policy. Legacy
`mirror_bottom` settings used alone retain bottom-only/no-mirror meaning;
conflicting explicit settings are rejected. CLI compatibility flags are tested.

The twelve new styles use native text, circle or segment objects. Their measured
native bounds feed the same multilayer zone-only keepout. No source board is
changed during planning and no existing counter is silently regenerated.

## Native checks

Windows, KiCad 10.0.6, bundled Python 3.11.5 and wxPython 4.2.2:

- All 26 native core/UI/CLI tests passed in 22.545 seconds, normal exit.
- Midpoint mirroring is checked for every style on 2, 4, 6, 8 and 32 layers,
  using both planned labels and actual `PCB_TEXT.IsMirrored()` properties.
  Subset selection retains physical numbering and full-stack orientation.
- Existing all-style 2/6/32-layer tests exercise read-only planning and exact
  Add/Undo/Redo. Native group move/save/reopen, stale state, partial failure
  rollback and real filled-zone exclusion remain covered.
- A four-layer saved/reopened board retains L3/L4 mirrored. CLI cases check
  policy selection, candidate/source protection and conflicting flags.
- New style frames and layout positions are checked for distinct geometry and
  complete keepout containment. Native UI tests select every added preset.
- The shared live/off-screen canvas drawing path is checked for visible native
  copper glyph colours and opaque image output.

## Preview provenance and limits

Window capture produced blank images and the desktop capture helper could not
initialize. Those attempts were not accepted or copied into the plugin.
`help-preview.png` and `help-styles.png` instead use the same native
`CounterPreview.draw` path used by the live canvas, with native copper glyph
polygons generated from actual detached `PCB_TEXT` objects. They are off-screen
preview renders, not live window screenshots. The gallery shows all twelve
added styles on a synthetic four-layer board; L3/L4 are mirrored throughout.

The native board fingerprint remains unchanged during rendering. No private
design, local folder, generated illustration or manually edited numerical
content is included. Manufacturing feature size, edge spacing, netless copper
and possible track/pad crossings still require designer/fabricator review.

Earlier published versions remain unchanged. Candidate feed metadata is held
until the release assets have been published and their hashes verified.

## Publication

Published [3.6.36](https://github.com/wayri/WayriCAD/releases/tag/v3.6.36)
from `b01ec674ae4230dcd70a0e073e209a7bb13d556b`. All eight
[exact-source CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40455320912)
passed, including Linux, Windows and macOS portable checks and PI references.

All 24 PCM ZIPs pass schema, runtime/action, syntax, icon and hash validation.
The independently extracted Layer Counter passed all 24 style plans, native
GUI default orientation and CLI candidate save/reopen with L3/L4 mirrored. GUI
and CLI were exercised in fresh processes; mixed application-lifetime harness
attempts were not counted as successful installer acceptance.

The wheel passed isolated CLI/report/mechanical smoke checks and excludes tests
and bytecode. Its layer-counter modules match source. The source archive has
1,344 tracked members matching the tested checkout. Three root version checks
with 24 subtests and 32 Analytics packaging checks passed.

All 31 assets were downloaded and compared to the local SHA-256 manifest before
publication. Public Layer Counter and feed downloads were checked afterward;
the PCM feed is promoted from those exact release metadata bytes. Existing
release assets and tags were preserved. No local plugin installation was made.
