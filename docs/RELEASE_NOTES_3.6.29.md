# WayriCAD 3.6.29

This incremental release simplifies Constraint Studio, fixes two Fanout problems
found on Marble, and refreshes the suite's guides and screenshot showcase.

| Change | What to expect |
|---|---|
| Constraint Studio | Ordinary rule creation/editing and condition building move back to KiCad's Design Rule Editor. Netclasses and board-wide settings stay in Board Setup. Studio's overview is read-only in both visual and native interfaces. |
| Retained Studio workflows | Protocol presets, clearance-matrix generation, reusable sets, BGA managed regions, scoped layer/via profiles and reviewed export/apply remain available. Old generic editing bridge commands are rejected without changing the workspace. |
| Fanout project loading | Saved projects containing null netclass assignment/pattern collections no longer crash the planner. |
| Existing-route protection | Fixed-mode escapes reject pads already touching same-net routing on their copper layers. Adaptive open-stub continuation and Via-in-pad retain their separate checks. |
| Guides and screenshots | All 24 plugin guides have clearer navigation. The main README adds a compact showcase, retains larger previews and includes the new read-only Studio overview. |

## Dense-board Fanout limits

Marble trials did **not** validate full BGA or residual connector fanout. The
locally unrouted 361-pad BGA and partly routed active connector cases produced
no accepted escapes. The 400-pad FMC connector search timed out at 120 seconds.
Conservative zone envelopes, existing topology and clearance limits remain
important restrictions. No clearance was relaxed or failed plan forced onto a
board. Original files remained unchanged.

The two reproduced bugs are fixed; this release does not claim that dense-board
fanout is complete. See the [trial report](audits/FANOUT_REAL_BOARD_TRIALS_2026-10-23.md).

## Install or update

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, install the
updates and restart PCB Editor. Each plugin can also be installed from its PCM
ZIP without unpacking it. All 24 packages are included; the 18 IPC packages use
3.6.29. Independently versioned native packages receive patch updates because
their bundled guides/screenshots changed:

| Native package | Version |
|---|---|
| Trace Refiner | 0.3.2 |
| Project Fusion | 0.9.12 |
| Variant Manager | 0.6.5 |
| Component Arranger | 0.1.4 |
| Layer Counter | 0.1.4 |
| Silkscreen Label Placer | 0.3.4 |

Their existing functional behavior is retained. Earlier published assets are
unchanged. Packages remain marked **testing**.

## Validation and scope

Constraint Studio passed 395 plugin/documentation regressions, 27 native wx
checks and actual native/WebView workflow checks. Native DRC processed the
exported demonstration and reported fixture violations; it was not a clean DRC
result. The Fanout changes passed 87 native routing tests. These checks used
Windows and KiCad 10.0.6; they do not establish compatibility on every OS or
connected-editor workflow.

- [Constraint Studio changes and native evidence](audits/CONSTRAINT_NATIVE_OVERLAP_2026-10-23.md)
- [Release packaging and CI evidence](audits/RELEASE_3.6.29.md)
- [Screenshot provenance](audits/README_GALLERY.md)
