# PI/SI Live Acceptance For 4.8.5

Validated on 16 November 2026, Windows, KiCad 10.0.6 bundled Python 3.11.5,
wxPython 4.2.2. A disposable two-net routed board, private KiCad configuration,
documents/cache and private IPC namespace were used. No normal KiCad settings
or user board was changed. The editor was terminated after the test.

## Live Checks

All 18 assertions passed against the actual editor API, without mocking IPC:

- Exact originating saved-board identity and authenticated instance token.
- Four exact selected-pad UUID readbacks, including a two-net selection.
- Automatic net following in both PI and SI.
- Explicit PI source and load pad assignment.
- SI does not infer terminal direction from one selected pad.
- PI-to-editor and SI-to-editor exact object selection.
- Two-net ambiguity retains existing PI/SI inputs; later valid selection recovers.
- Saved-board SI study and PI DC solve complete using real worker processes.
- Saved copper hash is unchanged by selection and analysis.
- Both tools reject a changed saved source before further cross-selection.

The PI fixture used explicit 35 um outer copper at z=0.0175/1.5825 mm. Its
initial missing-stackup rejection was correct; no nominal thickness was silently
introduced into the production solver. SI exercised a routed two-via path.
The study establishes scoped integration, not arbitrary-board or protocol signoff.

## Fixes And Other Checks

Native regression testing exposed standalone follow controls attempting IPC
without an originating editor and overwriting useful analysis status. Both tools
now enable automatic follow initially only with a complete launch identity.
Standalone-state regressions were added; the final native set passed 14 tests.

Independent review found dense reference frequencies losing exact matches and
extreme finite data overflowing plotting/probe calculations. Exact matches now
take precedence, unrepresentable magnitudes are rejected and log-distance
probes avoid ratio underflow. Four focused regressions cover these cases.

An async native test initially timed out before scientific imports/event-loop
activation. Rechecking with an active wx event loop and warmed imports passed
without changing its timeout or numerical baseline. Live timers ran with an
active native event loop, not a mock scheduler.

## Evidence Boundaries

Desktop screenshots returned an unrelated foreground window; they were rejected
as evidence. No new visual screenshot acceptance is claimed. Existing native
layout tests cover compact/minimum sizes, visible controls and result lifetime.
Automated API selection is not a claim that every mouse hit-test is accepted.

Source selection maps to a saved snapshot, not unsaved editor geometry. MQS and
quasi-TEM cavity limits in the release notes remain; no Palace speed/accuracy
comparison, full-wave qualification or hardware measurement is claimed.

## Storage

Test scratch and retained receipts are on D:. Dependency preflight unexpectedly
provisioned two task-owned runtimes under the default C: cache. Setup was stopped;
subsequent downloads were disabled and scratch directed to D:. Those two new
runtimes were enumerated with file hashes and removed after their processes
ended; pre-existing runtimes and the shared pip cache were preserved. The local
cleanup receipt retains measured byte counts and before/after capacity. This
does not establish the required 100 GiB reserve on C: or an OS-enforced quota.

Release CI and artifact identity are recorded separately in the published
`validation-4.8.5.json`; this source document is not itself a hosted-CI receipt.
