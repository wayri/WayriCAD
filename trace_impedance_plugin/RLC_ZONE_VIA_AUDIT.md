# RLC Zone, Via And Stub Coverage For 4.8.5

## Scope And Implemented Behavior

This is a source audit and focused safeguard change on the 4.8.5 candidate,
not new whole-board electromagnetic qualification. No board copper is edited.

| Area | Implemented | Still missing / not claimed |
| --- | --- | --- |
| Zone connectivity | Native filled islands with holes, layer-aware contacts, connected pad/thermal copper and finite-width corridor navigation. Disconnected corridors remain unresolved. | Certified arbitrary copper union/connectivity, all track crossings, unions across independently represented overlapping zones and general spreading current. Conservative false disconnections remain possible. |
| Zone electrical terms | Corridor DC/skin resistance, first-order corridor inductance and reference-overlap capacitance with explicit saved dielectric evidence. | Arbitrary-zone characteristic impedance, full return-current distribution, mutual coupling or full-wave fields. Full-island C and corridor R/L are not one extracted series circuit. |
| Via geometry | Physical TopLayer/BottomLayer span in saved copper-stack order, independent of unflashed internal annuli. Through, blind, buried and microvia geometry labels. | Microvia taper, stepped/backdrilled barrel physics. Backdrilled/secondary-drill geometry is rejected, not approximated as one cylinder. |
| Connected via terms | Selected traversed length between saved copper midplanes, circular barrel resistance with assumed plating, skin loss and isolated partial inductance. | Antipad/pad capacitance, complete return-loop inductance, mutual coupling, transition Z0 and broadband channel prediction. End-face half-copper overhang is not included in the length convention. |
| Remaining barrel | Length and endpoint layers beyond the selected path span; separate `remaining_barrel` records. | Automatic proof that the residual is electrically open rather than attached to another branch. Termination remains `unverified_open_stub_or_connected_branch`. |
| Stub parasitics | Explicit unknown `capacitance_pf`, `input_impedance_ohm` and `resonance_hz`; `VIA_STUB_OR_BRANCH_UNMODELED` blocker. | A numerical shunt C, resonance, transmission-line stub response or measured/validated S-parameters. No such approximation is added in this change. |
| Whole-board/bulk | Every physical barrel slice retains its physical-span provenance. Zone islands remain listed pending terminal/corridor review. | A selected connected span cannot be inferred from an isolated bulk slice, so residual/stub classification is `not_evaluated_without_terminal_path`, not fabricated per slice. |
| Route ambiguity | Connected-graph branch/cycle diagnostics after ideal contacts collapse; chosen candidate remains visible with `ROUTE_AMBIGUOUS`, partial status and no passing uniform-route impedance. | Arbitrary branching-net equivalent RLC or current distribution, and a guarantee that every geometrically possible route was discovered. |
| Reference semantics | Actual adjacent filled-copper coverage is still required. Overlapping candidates on one layer are not silently selected. Explicit non-ground references retain an unverified-electrical-role blocker. | Net names or geometric coverage alone do not prove an AC return connection. |

## Numerical And Status Contract

Only the connected path's via length contributes its existing series barrel
R and isolated partial L. Remaining barrel is not silently appended to those
series totals: open/branched structures need a different circuit boundary.
Even a through traversal with no remaining extension stays partial because
antipad capacitance and return-loop behavior remain unknown.
The frequency sweep retains traversed-copper resistance curves, but suppresses
series reactance/magnitude and reports `PARTIAL` when route ambiguity or a
remaining via extension is present. It does not turn the available barrel L
into a complete frequency-domain channel model.

Via length now requires complete positive saved thicknesses over its span.
Missing stackup data raises an actionable error instead of distributing board
thickness equally among copper layers. Different blind/buried layer pairs
therefore do not silently receive equal depth. Duplicate endpoint labels are
rejected; ideal pad contact nodes are tied to physical UUIDs rather than merging
separate pads with the same number. There is no all-net aggregate fallback.

The existing barrel approximation is documented in the primary
[TI Analog Engineer's Pocket Reference](https://www.ti.com/seclit/eb/slyw038d/slyw038d.pdf).
It supplies an isolated via-inductance estimate, not a stub/channel model.
No new numerical via-stub approximation is introduced, so no lumped capacitance
or resonance is presented as broadband validation. Any future such model needs
reviewed antipads, reference/return geometry, termination and applicable primary
technical references plus separate analytical and independent validation.

## Focused Verification And Integration Gate

`tests/test_via_geometry.py` covers nonuniform stackup distances, full through
traversal versus blind/buried/microvia spans, partial-through residuals, reversed
traversal, two residual extensions, bulk-slice semantics, unknown stub terms,
backdrill rejection, duplicate endpoint labels and graph ambiguity. Optional
native KiCad tests construct synthetic in-memory boards to exercise through,
blind and microvia paths, finite filled-zone corridors, disconnected islands
and native route branches. They do not open a live editor or establish measured
parasitic accuracy. The small filled-zone fixture uses supplied native polygons,
not a validation of KiCad's zone-filling algorithm.

Focused Windows verification used the installed KiCad 10.0.6 Python interpreter:
all 20 methods in the new geometry/safeguard suite passed. The broader source
run (plugin tests plus root RLC model/CLI tests) recorded 95 passed, 7 skipped
and 42 passing subtests, initially with one failure: canonical/SI bundled
engine equality. After synchronization and GUI-feedback integration, the broader
suite passed 97 tests with 8 skips; the separate SI suite passed 221 tests with
39 skips. These counts overlap and are not summed. Source-only documentation
validation passed. These checks
do not include a live editor, package extraction, measurement comparison or
hosted CI for this patch. The initial subprocess test encountered an invalid
Windows inherited input handle under pytest capture; it passed with capture
disabled, without changing the test or numerical code.

The canonical `measurement.py` and `copper_path.py` are also vendored into Quick
SI. Their sibling copies are outside this task's ownership and must be
synchronized by the integrator using the repository's preparation workflow,
then the copy-equality gates and affected SI/native tests rerun. Do not publish
with canonical/bundled drift or reuse the earlier CI result as evidence for
these changes. The integrator synchronized those two files byte-for-byte. The
legacy all-suite preparation script still hardcodes historical package versions,
so only its deterministic engine-copy operation was applied; package metadata
was not regenerated with that stale script. Final equality/CI evidence is recorded
in the release receipt. This audit does not grant release approval.
