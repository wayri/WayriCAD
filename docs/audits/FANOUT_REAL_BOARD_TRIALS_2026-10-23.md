# Fanout trials on public Marble — 2026-10-23

Representative trials are complete. They exposed two source defects, now fixed,
but **did not validate complete BGA fanout or residual functional routing on
Marble**. Both deliberately derived local-unrouted/partial-route cases returned
zero accepted escapes. No rejected or empty plan was forced onto a board, and
no original design was modified.

## Source and native evidence

Public [Berkeley Lab Marble](https://github.com/BerkeleyLab/Marble/tree/a426777d92c0f22a546d4740b419a3937e0c1f90/design),
using the repository's existing native KiCad working copy. Windows / KiCad
10.0.6 / bundled Python 3.11.5. Source board SHA-256:
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
Matching project SHA-256:
`e6f28cc276ea7b2dda702cd2daaf7a2b4fc97e06916971c9b127acbd465bf55c`.
No same-stem custom-rule file was present. All experiments use private copies;
the public source files remain the reference.

The board has 1,006 footprints, 41,044 tracks/vias, 127 zones and 12 copper
layers. U1 is a 676-pad BGA; U35 is a 361-pad BGA. P1 and P2 have 400 net-assigned
connector pads each. J11 has 14 plated pins; J9 has 12 SMD pads. Some J9 nets are
explicitly named `unconnected-(J9-Pad...)`, so lack of a track contact alone is
not evidence that a required connection remains unrouted.

Native baseline DRC ran on a detached copy with `--all-track-errors`,
`--severity-all`, `--refill-zones` and `--save-board`. Execution completed in
116.687 s, exit 0, with 489 findings (53 errors / 436 warnings) and zero reported
unconnected items. Existing findings include 59 dangling tracks, 26 starved
thermals, 67 silk-over-copper findings and **199 library-footprint issues**, which
reaches the native reporting cap. No clean-board or complete library-coverage
claim follows from these totals. Seven inherited ignored-check categories
remain unchanged: missing/malformed courtyards, track centering on vias, tuning
profile geometry, footprint-filter mismatch, and PTH/NPTH inside courtyards.
The CLI emitted registry-access warnings; it nevertheless produced the native
JSON report and saved the refilled detached board. The matching project bytes
were unchanged. Post-refill baseline board SHA-256:
`5e7b588ae006ccc77fb823e982cc504aab9c17b939e3bbec61e106fb89e77bce`.

## Strict saved-netclass plans

These plans use ordered groups for all seven saved netclasses. Track width,
clearance, via diameter and drill come from the matching saved class; no local
clearance override is used. Dimensions remain subject to native DRC. Plans run
in isolated native workers with a 120-second whole-job bound. Durations include
snapshot/loading/source checks and can overlap other validation jobs; they are
not controlled performance benchmarks. The table records the phase after the
nullable-netclass fix and before the new Fixed existing-route guard; the guard
recheck is reported separately below.

| Scope and mode | Accepted / rejected | Time | Interpretation |
|---|---:|---:|---|
| U1, all 676 pads, Fixed Dogbone outward, 0.5 mm reach | 0 / 676 | 8.407 s | 366 existing-via overlap, 305 other-net via-clearance failures, 5 zone/keepout failures |
| U35, all 361 pads, Fixed BGA/LGA grid outward, 0.5 mm reach | 0 / 361 | 8.484 s | 254 existing-via overlap, 105 other-net via-clearance failures, 2 zone/keepout failures |
| P1, all 400 eligible connector pads, Connector edge | No result | 120.234 s | Whole-job timeout; worker terminated, no partial plan applied |
| J11, all 14 plated pins, Connector edge | 0 / 14 | 61.875 s | All pins reached the bounded connector search budget |
| J9, all 12 pads, Fixed radial, 1 mm, no new vias | 7 / 5 | 9.625 s | Two already-connected GND pads plus five intentionally unconnected pad nets; not residual functional routing |
| J9, all 12 pads, Adaptive | 5 / 7 | 10.172 s | All five accepted pads have intentionally unconnected net names |
| J9 active nets `/MMC/*,GND`, Fixed radial, 1 mm, no new vias | 2 / 3 | 10.625 s | Both accepted pads already touch existing native routing; this is not “fanout only the rest” |
| Same J9 active scope, Adaptive | 0 / 5 | 10.141 s | Explicit same-net-zone, ambiguous/branched launch and existing-via/open-endpoint topology guards |

The routed original BGAs are not suitable evidence of full new BGA fanout
completion: their existing copper and vias occupy the proposed escapes. A
derived local-unrouted copy below is a distinct experiment with declared
removals rather than a hidden change to this source.

## Concrete defects found during intake

1. Valid saved KiCad project data had `netclass_assignments: null`. All initial
   strict grouped plans aborted in `pad_in_netclass` on `.get` of that null
   value. The shared reader was fixed to normalize nullable assignment/pattern
   collections, and the plans above were rerun afterward. The source project
   was not rewritten to work around the bug.
2. Fixed generic fanout could propose additions from pads that already had routed
   copper. The J9 active-net trial reproduced this with two accepted proposals;
   Adaptive rejected those existing topologies. These proposals were not
   applied. Fixed mode now rejects
   same-net endpoint/interior copper contact on pad copper layers before Fixed
   generic escapes; Adaptive open-stub continuation and Via-in-pad remain
   separate contracts. Repeating the exact active-J9 Fixed settings after the
   fix produced **0 accepted / 5 explicit connected-copper rejections** in
   11.203 s, with no source changes. These source fixes are in commit
   `79870cbb`; this audit does not assert that older released binaries contain
   them.

## Deliberately derived partial/unrouted copies

These are altered **test copies of Marble**, not an account of the original
board's routing state. Pads, footprints, placement, net assignments and matching
project bytes were preserved. No zone, clearance, layer policy or fabrication
floor was relaxed to obtain acceptance.

### Full U35 BGA scope after local routing removal

The test copy removes copper items belonging to U35's pad nets only when their
complete native bounding envelopes lie inside the U35 courtyard/body-hull
bounding rectangle, X 236.355–254.445 mm and Y 173.755–191.845 mm, on all copper
layers. This declares the local unrouting boundary; it is not a production ECO.

- Removed **880 tracks and 297 vias** (1,177 objects).
- All **39,867 unremoved original copper objects** retained their exact UUID,
  type, net, endpoints, width, layer and relevant drill/span/arc geometry.
- Global pad/footprint geometry and identity digest remained unchanged,
  including after native save/load. Matching project hash remained unchanged.
- Derived PCB SHA-256:
  `1da32b0f52493d2562c13dd63b1fd34fcd84324f618f3df936e0ed4f23aa3a2c`.

The full **361-pad** Fixed BGA/LGA grid attempt used the saved netclass dimensions
and 0.5 mm reach. It completed in **10.719 s** with **0 accepted / 361 rejected**:
281 other-net via-clearance failures, 79 zone/keepout failures and one retained
existing-copper connection. The derived PCB remained unchanged during planning.
This is a failure to find a legal full escape in the configured candidate
family, not proof that the physical BGA is unroutable. Other candidate families
and dimensions were not exhaustively tested.

### J9 with a missing launch and retained short stub

The second test copy removes exactly two original tracks:

| Original UUID | Deliberate test change |
|---|---|
| `6bfef99e-818d-46f0-977f-216149d861fc` | Remove pad 4 `/MMC/I2C_PM_SCL` launch |
| `5508c5c2-b4eb-44a9-a54c-c9a213df11d8` | Remove the upstream pad 6 `/MMC/PWR_ALERT` segment, retaining its short pad-connected diagonal |

All **41,042 unremoved original copper objects** remained exact; global
pad/footprint geometry and identity were unchanged, including after native
save/load. The project hash stayed unchanged. Derived PCB SHA-256:
`c0a44e153ab3b39f822bc61e256d97315a2c7dd70e6ad6cabb00d20342fa79dc`.

Adaptive planning over all five active J9 pads (`/MMC/*,GND`), 1.5 mm search
radius and 0.25 mm step completed in **12.766 s** with **0 accepted / 5 rejected**.
Each rejection was explicit: same-net-zone topology, unresolved existing pad
launch, exhausted zone/keepout search, ambiguous/branched contact, or existing
via/open-endpoint topology. A retained short pad-connected segment was therefore
not silently treated as a supported, unambiguous open stub. Planning left this
derived board unchanged.

## Validation verdict and remaining limitations

| Check | Result |
|---|---|
| Original public board/project hashes after all trials | PASS — exactly match the source hashes above |
| Unremoved copper and pad/footprint geometry in both derived copies | PASS — exact native records and saved-file round-trips |
| Native original-board baseline refill/DRC execution | PASS execution; 489 inherited findings, capped library category and ignored checks disclosed above |
| Full original/derived BGA completion | NOT VALIDATED — no accepted full-scope escape plan |
| Residual active routing on original/derived J9 | NOT VALIDATED — original duplicate proposals now blocked; derived Adaptive scope produced no accepted result |
| Apply, post-Apply refill, before/after candidate DRC and connected-terminal partition comparison | NOT RUN for these real-board cases — no accepted functional residual plan to apply |

The planner's `zone/keepout` gate uses conservative zone bounding envelopes,
rather than exact filled-copper polygons and their voids. Adaptive topology
guards also use same-net zone envelopes. This implementation fact can explain
over-rejection in dense filled boards, but no native check here proves that any
particular rejected escape would be safe. Other-net via clearances and retained
surrounding copper remain real constraints. Zero accepted candidates must not be
presented as full fanout success, nor as a proof that no feasible routing exists.

The integration run recorded **87 passing native routing regression tests**,
separate from these real-board outcomes. This task independently reran three
focused nullable-netclass / Fixed endpoint-interior-contact / other-layer-and-
through-pad regressions: **3 passed in 0.069 s**. They verify the two fixes; they
do not qualify full BGA or dense connector completion.

Raw settings, plans, source hashes, timings, native reports and logs remain under
the local `.validation/fanout-real-boards-20261023` evidence directory. They are
not bundled release assets and can contain local workspace paths.
