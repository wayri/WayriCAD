# WayriCAD 3.6.31 release validation

Windows source checks use Python 3.14.2. Native controls use KiCad 10.0.6,
Python 3.11.5, wxPython 4.2.2 and wxWidgets 3.3.2. Public Marble source bytes
remain unchanged; no private user project was edited.

[Live-current evidence](QUICK_PI_LIVE_CURRENT_2026-10-24.md) documents the linear
model, measured times, numerical checks and sliver-mesh limitations.
The shared source suite passed 596 tests, with 123 skips and 464 subtest passes.
Quick PI passed 351 tests, with 56 skips and 399 subtest passes before the
final gesture-only update; its final native wheel/inspector/canvas matrix
passed 19 tests. Plain zoom, Ctrl-only load adjustment, acceleration, reversal,
fractional deltas, stale inputs, latest-result publication and probe/camera
retention were checked. Source/native runtime and skipped cases remain distinct.

All 24 versions advance to distribute shared probe refresh support. Exact-source
CI, package schemas, isolated archive/wheel checks and public download/hash
verification are release gates. Publication identifiers and verification are
recorded after completion. Existing release tags and binaries remain unchanged;
the public PCM feed is promoted only after asset verification.
