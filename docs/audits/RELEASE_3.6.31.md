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

## Published verification

- All eight [CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40017847490)
  passed for source commit `d5925fd0`; the release tag identifies that commit.
- All 31 public release assets were downloaded and matched the validated local
  SHA-256 hashes before feed promotion. The 24 independent PCM ZIPs passed
  official schemas, payload syntax, icons, entrypoints and candidate feed hashes.
  Full documentation and 26 release-contract tests / 24 subtests passed.
- The rebuilt wheel passed isolated CLI/report/assets/local-server checks.
  Inspection covered 26 archives / 5,777 files without validation caches or
  known private paths. All 1,245 tracked source-archive members match source;
  the live-current tests and analytical fixtures are included.
- The extracted Quick PI ZIP passed 11 GUI/plot tests and three numerical/report
  tests in separate fresh isolated processes, both exiting normally. Loaded
  production files matched the ZIP bytes; unchanged source tests were copied
  separately from installer contents. Source native controls passed 19 tests.
  Synthetic temporary boards were used; installed live-editor IPC and native
  Linux/macOS UI remain unverified.
- A combined custom report/GUI harness completed all 14 functional checks but
  timed out at native interpreter shutdown. Normal standalone GUI/report process
  lifetimes passed without forced exit; this harness limitation remains recorded
  rather than claimed as a successful combined-process check.

PCM feed promotion follows asset publication and download verification as a
separate maintainer commit. Existing tags and release binaries are unchanged.
