# WayriCAD 4.2.0

This release adds a dedicated DFM/DFA workspace, reusable manufacturer checklists,
whole-board RLC section extraction and PI series power trees. KiCad 10 remains the
native validation target. KiCad 11 acceptance and several live editor workflows
remain pending, as detailed below.

## DFM / DFA Studio and sourced checklists

The Manufacturing Readiness package now has a separate **DFM / DFA Studio** action.
The existing manager retains its project DRC, jobset and manufacturing-release
archive workflow.

The initial catalogue has **21 process presets: 20 with native numerical rules
and one manual PCBWay recommendation checklist**, alongside **28 manufacturer
directory entries**. A directory entry without a preset has no runnable limits.
PC Process, Krypton Solutions and other entries requiring supplier confirmation
do not inherit another manufacturer's rules. This is a sourced screening
catalogue, not complete coverage or approval from all major manufacturers.

Profiles retain service, source dates, layer count, material, thickness, finish
and applicable copper scope. Starting copper, finished copper and a supplier's
order-option label are distinct; required inner-copper weight is recorded
separately. Unknown or mismatched scope blocks native-rule compilation.

Checklists save/load the selected process, source/profile-bound results, attached
evidence and separate waivers. Process changes invalidate old evidence. Equivalent
integer and float representations of a quantity keep the same context identity.
Manual requirements need an explicit evaluation with evidence; a note or waiver
does not silently make a check pass.

Native vendor checks run on a private saved-design copy. The original PCB,
project and custom rules remain unchanged. The copy uses the reviewed vendor
rules, enables their relevant native check providers and clears saved DRC
exclusions. These overrides are recorded so ignored project checks cannot hide
vendor violations. Duplicate unconditional native constraints are rejected to
prevent KiCad's last-match precedence from hiding a limit. Ordinary project DRC
remains a separate check. Manual-only presets explicitly run project DRC and
keep vendor-specific requirements unknown.

The workspace adds family/status/layer filters, linked UUID findings, saved-copper
selection, pan/zoom/focus controls and native straight-track width dimensions.
Optional background checking watches saved changes and schedules one cancellable
worker. Unsaved editor changes are outside that snapshot. HTML/PDF reports retain
the requirements, native findings, process and sources with a paired JSON file;
screen filters do not remove report content.

[DFM/DFA workflow and limits](../manufacturing_readiness_plugin/DFM_DFA.md).

## RLC: all nets, bundles and reference planes

**All nets / Bundles…** and `wayricad-rlc bulk` extract routed trace/arc and via
sections across the saved board, selected nets or portable named bundles.
Branches retain physical section identities and endpoints. Budget or cancellation
limits produce an incomplete result with omitted identities.

Optional reference inference checks actual saved filled islands on adjacent
copper layers and records coverage and dielectric evidence. Ambiguous candidates,
unfilled geometry, missing stackup data and unknown electrical return roles stay
visible. A plane's geometric coverage does not establish its AC return connection.

Results and reports keep bundle/net/path headers and per-section R/L/C/Z0 where
the existing models apply. Mixed or branched nets have no single inferred uniform
impedance. Bundle grouping does not extract coupled impedance, mutual L/C or
crosstalk, and unresolved plane spreading remains outside the section model.

[Whole-board workflow, CLI and model limits](../trace_impedance_plugin/ReadMe.md#whole-board-sections-and-net-bundles).

## PI power trees, returns and setup fixes

Reviewed series paths can generate a topology preview and a solved power tree
in native output and HTML/PDF/JSON reports. Copper segments, parallel branches
and exact pin groups remain explicit. Supported node/stage data includes voltage,
current, drop, loss, input/output power and transmitted DC-power efficiency.
This efficiency is a path budget, not a converter-efficiency model. Missing or
infeasible values remain unknown; repeated-net copper budgets are not treated as
independent serial segments.
Standalone tree JSON export now rejects changed design/study inputs and protects
source files from overwriting. Unbound topology previews cannot save tree data.

**Batch studies…** and **Return paths…** now have separate entry controls.
Return-candidate detection ranks saved filled-zone coverage and requires an
explicit selection. Sampling provides local geometric evidence rather than
proof of a continuous electrical return loop.

Native runtime discovery reuses successful checks within one startup call.
SI neighbour analysis uses the native-only runtime path and loads scientific
route analysis only when needed. Thermal defaults can populate ambient, initial,
enclosure and fixed-face temperatures while preserving edited material properties.
Damped radiation Newton steps address excessive initial overshoot. Material
ratings and model limitations still apply. Large 3D solver performance requires
representative benchmarking; this release makes no general 3D speedup claim.

## Recorded validation and remaining work

- A targeted source check recorded **78 passes and 13 skips**. Skips are missing
  coverage, and this count is not the complete CI matrix.
- **12 hidden native controller checks** passed using KiCad 10.0.6/Python 3.11,
  including native CLI workers, cancellation, process save/load, numeric-context
  portability, filters and rendering. IPC transport was mocked for cross-probe
  boundary tests.
- Native KiCad 10.0.6 known-answer fixtures exercised track width, clearance,
  hole size, annular width and edge clearance, retaining named failing UUIDs and
  locations even when the original project's providers were ignored. Original
  design/project/rule hashes stayed unchanged.
- Direct native Python exporter checks produced approximately **41 kB HTML and
  69 kB PDF** for a synthetic DFM fixture. These sizes vary with the board and
  findings. The checks exercised the export API; native export dialogs remain
  outside that evidence.

Actual PCB-editor acceptance of the complete PI series run, setup/simulation
save and reload, both export dialogs, requested power-tree/return-path screenshots
and live cross-probing is still pending. KiCad 11 native acceptance is also pending.
The implementation does not provide complete automated fabrication/assembly
qualification, every manufacturer's private rules or a whole-board field solver.
Read the tool-specific guides and [compatibility record](COMPATIBILITY.md) before
using results for fabrication or electrical decisions.
