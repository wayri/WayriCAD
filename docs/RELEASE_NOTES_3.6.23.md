# WayriCAD 3.6.23

This batch includes Silkscreen Label Placer 0.3.2 and all 23 independently
installable WayriCAD plugins. PI, SI and thermal features from 3.6.22 remain
included.

## Silkscreen Label Placer

- **References only** is an explicit main-window choice. Manual board text,
  footprint text and value fields remain unchanged and still block placement.
  CLI previews support `--references-only`.
- Automatic sizing preserves already smaller text and its width-to-height
  ratio, subject to fabrication minimums. It no longer unnecessarily enlarges
  or widens references.
- Native rendered glyphs, including stroke and knockout backgrounds, define
  collision envelopes. Invisible font layout padding no longer consumes space.
- Nearby placements favour their own component and a common reading direction.
  Ambiguous or distant labels require checked guides. Routing considers
  alternative label/body exits and shares one visibility graph across them.
- Unresolved originals appear red and remain in the review after Apply. A
  timed-out whole-board replan no longer discards earlier accepted placements.

## Checks and limits

The native suite passed 94 tests. A synthetic 100-part assembly placed all
references horizontally and passed native KiCad DRC with zero findings. Testing
on a disposable copy of a supplied 852-part board produced 261 corrections,
all horizontal, with no new DRC type/item combinations. Independent checks found
no accepted glyph envelope outside the board or intersecting pads/courtyards.
Manual text and source bytes were preserved; exact undo was verified.

Placement remains a bounded local search. That whole-board run left 288
references unresolved; they retain their old positions and can retain old
violations. A focused five-reference selection corrected four cases. These
results do not guarantee that every dense board can be annotated automatically.
Review unresolved items and run native DRC before saving.

## Install

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, install
updates and restart PCB Editor. Alternatively download the desired PCM ZIP and
use **Install from File**, without unpacking it.

The 17 IPC packages are 3.6.23. Native versions are Silkscreen Labels 0.3.2,
Fusion 0.9.11, Variant Manager 0.6.4, Trace Refiner 0.2.3, Component Arranger
0.1.3 and Layer Counter 0.1.3. Unchanged native packages retain their existing
versions; earlier published assets are preserved.

[Release validation](audits/RELEASE_3.6.23.md) ·
[Silkscreen validation](audits/SILKSCREEN_ASSOCIATION_0.3.2.md) ·
[Silkscreen guide](../silkscreen_label_plugin/README.md) ·
[Previous analysis improvements](RELEASE_NOTES_3.6.22.md)
