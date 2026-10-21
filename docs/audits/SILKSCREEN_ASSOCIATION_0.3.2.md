# Silkscreen placement corrections — 0.3.2 candidate

Validation date: 2026-10-22. This is a source/installable candidate, not a new
published suite release. The public PCM feed and existing release assets are
unchanged.

## Corrected behaviour

- Explicit **References only** main-window selection preserves manual board and
  footprint text and value fields. Preserved text remains a placement obstacle.
  The CLI `--references-only` flag overrides custom text categories.
- Automatic sizing does not enlarge a smaller existing label unless the user or
  native minimum requires it; stroke growth is likewise avoided. Condensed or
  stretched lettering keeps its original width-to-height ratio.
- Rendered native glyph polygons, including full stroke and knockout geometry,
  define the text envelope. Invisible font layout padding no longer consumes
  otherwise usable space. Clearance still surrounds the entire glyph rectangle.
- Legal, unambiguous originals are kept where possible. Other nearby slots are
  ranked by distance to their own body. Candidates closer to another component
  by more than 0.2 mm, or more than 2 mm from their owner, need a checked guide.
- Guide routing tries alternative clear label/body exits and one wider bounded
  multi-source visibility graph when a necessary detour around a group was pruned from the
  small graph. Every segment retains board, pad, body and silkscreen checks.
- Local search reserves some time for distant guided slots; it no longer
  discards successful assignments by restarting a complete plan near timeout.
- Unresolved originals are red in the preview. Apply retains their review and
  count instead of reporting partial placement as a complete correction.

## Evidence

Windows, KiCad 10.0.6 native Python/wx runtime. Tests do not establish other
platforms or KiCad 11 support.

| Check | Result |
| --- | --- |
| Native plugin suite | 94 tests passed, including actual native window controls, glyphs, rollback and undo/redo |
| Shared regression suite | 494 passed, 88 skipped, 227 subtests passed |
| Synthetic 100-part board with explicit courtyards | 100 placed, all horizontal; native DRC zero findings and zero unconnected items |
| Owner-supplied board, disposable copy only | 852 footprints; 720 eligible references; 261 changes, all horizontal; 432 accepted, 288 unresolved |
| Independent post-Apply geometry check on copied board | No accepted glyph envelope outside native board polygons or intersecting native pad/courtyard boxes |
| Copied-board DRC with explicit 0.2 mm silk clearance | 295 findings before, 294 after; no new type/item combinations; silk overlaps reduced from nine to eight |
| Original supplied-rule DRC | 286 findings before and after the earlier candidate; native silk clearance was zero, so positive-clearance validation was also run |
| Source custody | Source PCB hash unchanged; original project never written; manual text unchanged; exact in-memory undo verified |
| Final independent PCM | Official schema, native entrypoint/version, icon, Python syntax and payload privacy checks passed |
| Fresh extracted PCM process | Native import, placement, exact undo and references-only window at 850 px passed; source package not imported |
| Documentation | Source-only link/image validation passed |

The first shared-suite attempt encountered sandbox temporary-directory and
Windows file-replacement restrictions. It was rerun using a workspace temporary
directory and then outside those restrictions; the completed passing run is the
one reported above. No product acceptance checks were removed.

The native rendered-glyph contract intentionally replaces checks against font
layout padding. The mixed-size fixture was tightened from 3.4 mm to 2.95 mm pitch
because the old spacing no longer required shrinking. Negative fit fixtures now
use a 0.25 mm body-relative search allowance: the old 1 mm allowance contains a
real legal text/guide placement with the improved router.

A focused five-reference selection on the copied board corrected four cases,
including a formerly missed detour. The fifth remained unresolved. Whole-board
and selected-only results differ because bounded search time is shared across
eligible labels and the fixed surrounding text differs. This is a search limit,
not proof that unresolved labels are physically impossible.

## Screenshot provenance and limits

`silkscreen_label_plugin/help-reference-placement.png` is a generated raster of
the actual native `LabelPreview.draw` code for the public synthetic 100-part
fixture. It is not a desktop screenshot. It contains no owner board data, local
paths or personal identifiers. Earlier illustrations remain available.

A partial apply does not repair unresolved originals. Some retain pre-existing
pad, body, edge or text violations. Native DRC does not prove clear reference
association, and its remaining findings are not passes. The planner remains a
bounded conservative local search; it is not a globally optimal packing proof.
Private boards, raw reports and local copies remain outside version control and
release payloads.
