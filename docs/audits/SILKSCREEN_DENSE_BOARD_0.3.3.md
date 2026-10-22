# Silkscreen 0.3.3 — dense public-board exercise

Tested on Windows, KiCad 10.0.6 and its Python 3.11.5/wxPython runtime.
Immutable board sources and hashes are recorded in the
[reference-board study](SILKSCREEN_REFERENCE_BOARD_STUDY.md).
Only disposable copies were saved. No private project was used.

Default reference-only placement was used: leaders off, minimum height 0.8 mm,
normal courtyard target 2 mm, native manufacturing floors retained. Hidden and
locked references were preserved. Smaller original text is not permission to
override those floors. Forsten's original 0.5–0.6 mm labels therefore make this
a deliberately stricter placement exercise than their saved human layout.

| Board | Footprints | Eligible references | Accepted | Unresolved | Changed | Planner time |
|---|---:|---:|---:|---:|---:|---:|
| Marble | 1,006 | 182 | 170 | 12 | 112 | 46.2 s |
| Forsten FMCW3 | 429 | 417 | 241 | 176 | 241 | 527.0 s |
| Forsten VNA | 342 | 319 | 173 | 146 | 173 | 409.6 s |

Marble has 817 hidden references and seven visible references on locked
footprints. These are not counted as successfully placed. Search limits were
reached on all three boards. The results do **not** demonstrate one-shot closure
on extremely dense boards; unresolved originals remain unapproved.

All accepted rendered glyphs were independently checked against native pad/mask,
silkscreen, courtyard and board-outline geometry: zero violations in 170, 241
and 173 labels respectively. All accepted direct associations were independently
checked: zero required crossings. Three Marble virtual associations crossed
ordinary decorative artwork, which is permitted for unprinted associations;
no leaders were printed. These checks do not certify missing-courtyard body
proxies or physical package clearance. Native top/bottom preview renders were
reviewed; red unresolved originals remain visibly problematic.

Marble native DRC was 481 → 473 findings, with zero new type/item-UUID pairs,
eight removed silk-over-copper findings and zero unconnected items before/after.
Matching project settings were retained. Forsten native report totals decreased
(FMCW3 2,134 → 2,060; VNA 2,292 → 2,201), but these reports contain capped finding
categories and legacy UUID/zone conversion. Item-level comparisons are therefore
**inconclusive**, not evidence of no new DRC findings. Their original legacy
`.pro` files were retained; KiCad 10 interpretation is not qualified as identical
to the boards' original KiCad versions. No zone refill was requested.

Source hashes, manual text, hidden references, footprint/pad/copper/zone geometry
and exact in-memory undo assertions passed. A validation-script footer used an
obsolete native attribute name after those assertions; summaries were recovered
from saved plans/logs without rerunning the solver. Times above are solver-reported
times, not end-to-end workflow timings. Before/after HTML reports and native
preview PNGs remain local validation artifacts.
