# Dense-board fanout fixes — 23 October 2026

This follow-up replaces the failed planner outcomes in the
[initial public-board trials](FANOUT_REAL_BOARD_TRIALS_2026-10-23.md) with actual
fanout candidates and native checks. It does not claim complete autorouting.
All work used disposable public Marble copies; originals and saved rules were
preserved. Environment: Windows, KiCad 10.0.6, native Python 3.11.5.

## Causes and corrections

| Problem | Correction |
|---|---|
| Circular BGA pads, diagonal tracks and arcs treated as solid rectangles | Native effective copper shapes, including per-layer padstack geometry |
| Filled pour rectangles blocked virtually every through via | Ordinary pours refill around new copper; their old fill is not a routing keepout |
| Concave keepouts and holes treated as filled rectangles | Native polygon collision, retaining holes and disconnected islands; rule-area layer/track/via restrictions remain enforced |
| Same-net zone envelopes falsely implied a connected endpoint | Test actual filled material for adaptive topology checks |
| Short retained launch entirely inside its pad rejected as ambiguous | Continue from its outer endpoint without changing the retained track |
| Connector grid edges repeatedly scanned the whole board | Keep the planner's spatial index active and try validated direct exits before grid search |
| Every netclass group rebuilt the same obstacle index | Share immutable obstacle geometry within one grouped preview |
| BGA pitch centers missing from a user-selected search lattice | Add rotated package-pitch half-offset candidates to Adaptive search |

Native shapes supplement, rather than replace, post-Apply refill and DRC.
The IPC fallback remains conservative where the transport lacks native shapes.
No clearance reductions, netclass edits or ignored-check changes were used.

## Working BGA and partial-routing cases

| Scope | Initial trial | Fixed source |
|---|---|---|
| U35, all 361 BGA pads, Fixed grid outward, 0.5 mm reach | 0 accepted / 361 rejected; 10.719 s worker pipeline | 290 accepted / 71 rejected; 9.140 s worker pipeline, 1.797 s planner alone |
| J9, five active pins on a deliberately partial-routing copy | 0 accepted / 5 rejected; 12.766 s | Both deliberately disconnected signals escaped; 3 retained connections rejected; 2.859 s |
| J11, all 14 connector pins | 0 accepted / 14 search budgets; 61.875 s | 8 accepted / 6 existing-copper rejections; about 2 s |

The initial J9/J11 times include isolated-worker overhead; their new times
measure fresh planner calls. They are not like-for-like speed ratios. U35's
worker times use the same saved-board workflow; planner-only, application
startup, export and native refill/DRC times are separate. The derived U35 case removes local pad-net tracks and vias
inside its package envelope; it is an escape test rather than a claim that the
already routed source needs 290 extra vias. J9 removes one signal launch and
one upstream segment while retaining the other launch's short diagonal stub.
The successful J9 signals are `/MMC/I2C_PM_SCL` and `/MMC/PWR_ALERT`; intentionally
unconnected connector pins are excluded from this success count.

The fixed BGA plan adds 290 tracks and 290 through vias. Seventy proposed
locations still fail actual other-net copper clearance; one pad already has
retained connected copper. They are not silently accepted. A different reach
or adaptive search may find alternatives; no complete 361-pad escape is claimed.

## Native acceptance evidence

For the 290-escape U35 candidate, native zone refill and all-track DRC comparison
found **zero new errors**. Existing 39,867 copper objects, all footprints/pads
and project bytes were unchanged. Native pad connectivity partitions fell from
1,829 to 1,640, with **zero existing partitions split**. Reported unconnected
items fell from 341 to 152. The 103 added `via_dangling` warnings describe
escape ends that still need onward routing; they are not a completed board.

For J9, native refill/DRC found zero new errors and two added `track_dangling`
warnings at the new escape ends. Its two pre-existing incomplete connections
remain incomplete until onward routing is finished. Existing branch, via and
zone-connected pins were retained instead of duplicated.

Eight selected P1 FMC pins also produced eight escapes. Each initially had zero
native connected tracks and zero same-net filled-zone contacts. Native refill
and DRC introduced only eight `track_dangling` warnings and zero new errors;
all 41,044 original copper objects were unchanged by UUID, stable net name and
geometry. Native serialization can renumber internal net codes, so those codes
are not used as circuit identity. All footprint/pad/project data and pad
connectivity partitions were preserved. Solo native refill/DRC took 150.52 s;
it is separate from the approximately 3 s planning call.

Marble's inherited findings and ignored-check settings remain present. Library
findings reach KiCad's per-type report cap, so this is a comparison of affected
routing, not clean-board or library qualification. Original board SHA-256:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.

## Use and regression coverage

After Apply or opening a CLI/export candidate, **refill zones (B), then run
native DRC**. Planning does not rewrite existing copper or finish the net.
Reject rows identify unsupported topology, actual clearance failures and bounded
search exhaustion separately.

The affected native matrix passes 96 tests, including polygon holes, exact
circle/diagonal-track collisions, keepout preservation, short-stub continuation,
rotated BGA pitch candidates, grouped rules, connector search and CLI behavior.
Mask-only non-plated holes block copper on every layer, and cached shapes are
refreshed when a planner is reused after a board edit.
An additional source-runtime matrix passes 18 tests with 14 native-only tests
skipped and six subtests passed; skipped checks are not counted as passes.

## Whole-component second pass

After the release assets were frozen, the same extracted Fanout ZIP was tested
on the accepted 290-escape copy. Select the whole U35 component, retain its
saved per-netclass dimensions, choose Adaptive, radius 1.5 mm and step 0.2 mm.
With no pin-number filter, this planned another 35 escapes in 28.203 s and
reproduced the independently refilled/DRC-checked geometry exactly. The total
is **325 escapes across two passes**, not 325 completed nets or a single-pass
global route. The second preview reports previously escaped pads as retained
connections rather than adding duplicate copper.

The all-pad scope includes seven intentionally unconnected pad names. Separate
the counts: the first pass adds 285 active-pin escapes plus five NC-pad escapes;
the second adds 33 active-pin escapes plus two NC-pad escapes. Functional
routing evidence therefore covers **318 active pins**, not 325. NC geometry is
not counted as functional routing success; the two J9 and eight P1 successes
also exclude NC pads.

Native refill/DRC added four dangling-via warnings and zero new errors; reported
unconnected items fell from 152 to 120 (341 before the first pass). All 40,447
existing copper objects of the first-pass candidate and all footprints/pads and
project bytes were retained. The 35 additional escapes add 68 track segments
and 35 through vias. Pad connectivity partitions fell from 1,640 to 1,608,
with zero existing partitions split.

The 36 locations without a new second-pass escape remain explicit: 13 fail
other-net copper clearance; nine encounter same-net vias/arcs; 11 already touch
same-net zone copper; one would overlap a via; one would branch a generated
same-net route; one has an existing interior pad/track connection. These are
not waived or counted as newly routed. Original input hashes remain unchanged.
