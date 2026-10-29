# Board-derived RLC eye validation — 2026-10-30

This source update follows release 4.0.0. Existing published assets and the PCM
feed are unchanged; no binaries were replaced under an existing version.

## Model and boundary

Quick SI reuses its independently bundled RLC extractor. Ordered supported track
sections form distributed, frequency-independent RLC two-ports; section order
and impedance changes are retained. A Thevenin driver and explicit receiver R/C
terminate the cascade. Vias require user-reviewed loop L/C and use extracted
barrel resistance in identical pi equivalents. Extracted isolated partial via
inductance is not substituted for loop inductance.

The new channel requires whole-net topology verification before eye calculation.
Unmodelled stubs, zones, branches, missing reference coverage and unsupported
sections cannot fall back to a plausible-looking ideal eye. Nonuniform line Z0
does not itself invalidate a complete cascade. An unavailable requested eye
keeps its multi-net study incomplete.

Skin/proximity effect, dielectric loss/dispersion, return-conductor resistance,
roughness, pad/package/connector spreading, coupled aggressors and nonlinear IBIS
are not modeled. This is not LPDDR4 timing/ODT/training or compliance validation.
See [method, equations and limits](../../signal_integrity_advisor_plugin/BOARD_RLC_EYE.md).

## Checks performed

| Scope | Evidence |
|---|---|
| Full SI source suite, Windows / Python 3.14 | 206 passed, 37 skipped, 136 subtests passed. Skips include native KiCad workflows unavailable in that interpreter. |
| Focused numerical/study/shared runtime checks | 48 passed, 5 subtests passed. Includes DC divider, matched exact delay, subdivision invariance, passive power bounds, independent nodal via equations, receiver RC, long ringing, missing-data rejection and unavailable-eye study status. |
| Native KiCad 10.0.6 / Python 3.11.5 / wx / NumPy | 22 passed, clean exit. Includes six actual PCB extraction tests plus setup controls, old/new setup save/load, probes and viewport workflows. |
| Independent PCM test ZIP | Extracted package reproduced the saved native channel result exactly in an isolated process with no sibling RLC-plugin imports. It is an unpublished test artifact. |
| Native saved-board CLI | New receiver-capacitance option exercised on the synthetic board; simulated eye JSON and HTML exported successfully. |
| Documentation | Source-only documentation/image validator passed; figure visually inspected on an opaque background. |

Two initial subprocess checks failed because redirected Windows parent handles
were invalid; both passed when rerun with valid console handles. The complete SI
suite was then rerun successfully. No assertions, convergence tolerances or skip
conditions were relaxed to obtain passes.

Independent review found that the step export ended after a few UI even when
reflections required much longer to settle. The display now extends past the last
significant deviation from DC. Analytical and native lightly damped regression
cases verify the settled endpoint remains in the exported samples.

## Synthetic native PCB evidence and figure provenance

The fixture is a saved four-layer board with a 60 mm route and filled In1/In2
ground planes. Changing the actual width from 0.15 to 0.4 mm changes extracted
R DC from 0.19702857 to 0.07388571 ohm and section Z0 from 78.98082 to 48.72016 ohm.
Both eyes use explicit 1 Gb/s, 1 V open-circuit swing, 0.1 ns edge, 50 ohm source,
open receiver and 0 pF receiver C. Baseline and wider-route waveform refinement
errors are respectively 0.106 and 0.220 mV at 256 samples/UI (5 mV tolerance).

[The README figure](../../signal_integrity_advisor_plugin/help-board-rlc-eye.png)
plots those numerical results. It is a scientific plot, not a native-window
screenshot or measured-board eye. It contains no personal paths, identifiers or
private design data; no redaction was needed. The earlier Marble ideal-line
screenshot remains explicitly labelled historical.

First/cold extraction plus eye took 0.195 s; the following wider-route run took
0.060 s. They are different geometries and different import/cache states, so
these times are not an optimization comparison or suite-wide speed claim.

Local reproduction evidence is retained under `.validation/board-rlc-eye/`:
synthetic PCB copies, original-file hashes, source hashes, JSON/HTML results,
native log, figure generator and isolated-package check. The source PCB bytes
were checked unchanged around every native analysis. No user board was modified.
