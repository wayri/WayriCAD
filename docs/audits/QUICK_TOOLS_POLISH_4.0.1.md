# Quick PI / Quick SI polish — 4.0.1

## User-visible changes

Quick PI explains missing source/load selections, overlapping grouped contacts,
stale saved-board data and unsupported model combinations before Run. The toolbar
and Setup action share readiness and its tooltip. Guidance stays inside the
scrollable Setup pane; no additional viewport header is introduced.

Loss/probe tables copy a selected row with Ctrl+C, or the complete current table
with Ctrl+Shift+C. The context menu exposes both actions. Exported tab-separated
text retains the stored numeric precision rather than the shortened display
format; embedded line breaks and tabs cannot split a record. Sorting and native
selection identities remain in place, and leaving a row clears its hover text.

Quick SI derives its header from the completed report actually displayed,
including selected multi-net cases, rather than unrelated drafted main inputs.
It identifies route delay and Board RLC, ideal-line or unavailable eye results.
The full reason remains in the tooltip and Details. An unavailable requested
eye retains Route instead of forcing an empty plot. Input changes clear stale
model labels and numerical feedback with the previous result.

These changes do not alter the PI solver or SI channel equations. The previously
unreleased [board-derived RLC eye](../../signal_integrity_advisor_plugin/BOARD_RLC_EYE.md)
is included in the 4.0.1 packages, with its separate analytical and native
[validation record](BOARD_RLC_EYE_2026-10-30.md). Its DC-R / quasi-static-LC scope
does not include skin/dielectric loss, nonlinear IBIS or LPDDR4 training/ODT.

## Checks and scope

Focused native tests cover synchronized Run states, overlap/staleness recovery,
clipboard dispatch with a mocked clipboard, unchanged row selection, model-aware
eye navigation, numerical rows and displayed-case identity. The user's real
clipboard and PCB projects are not used. Viewport, setup persistence and result
probe tests retain their existing assertions.

The release procedure runs shared root tests, SI regressions, affected PI setup
and return tests, EMerge regressions, package/document validators and isolated
wheel smoke checks. CI includes the complete SI source suite in its existing
Windows/Linux/macOS matrix. Native tests use Windows, KiCad 10.0.6, Python 3.11
and wxPython 4.2.2. CI without KiCad is not proof of native compatibility on all
platforms; skipped checks remain skips. Exact counts and logs are recorded with
the release artifacts and the CI run linked from the release.

The independent ZIP/wheel checks cover bundled channel code, help and pictures;
no sibling install may supply missing backend modules. The fanout visual
catalogue now includes its nested PNG/JSON assets in the wheel as well as PCM.
Six unchanged standalone SWIG ZIPs retain their existing versions and are
compared byte-for-byte against the prior release.

## Screenshot provenance

The new opaque native captures are dated 2026-11-01. Existing larger screenshots
remain available in the READMEs with their original capture versions.

- [Quick PI](../../quick_pi_plugin/help-workspace-polish-4.0.1.png): native
  1280 × 860 window on a synthetic demonstration PCB with optional panels open.
  The 0.711492 mV field comes from the analytical 65 × 90 mm copper-plate test;
  the illustrated footprints are layout context and are not that solved geometry.
  This is a UI/result presentation fixture, not a measured-board validation.
- [Quick SI](../../signal_integrity_advisor_plugin/help-result-feedback.png):
  native 1280 × 800 window, 1212 × 546 eye canvas, actual extracted 60 mm
  synthetic route over filled references. Explicit inputs are 1 Gb/s, 1 V
  open-circuit swing, 50 ohm source, open receiver with 2 pF C and 0.1 ns edge.
  This is the linear board RLC model, not an IBIS or compliance result.

Original fixture PCB bytes are checked unchanged. Captures contain no personal
paths, private designs or credentials; no redactions were needed. Local capture
scripts and geometry/model receipts are retained in the ignored
`.validation/release-4.0.1/` evidence folder. No user design is packaged.
