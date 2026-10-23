# WayriCAD 3.6.28 release validation

This candidate packages the changes through `77f81f73`, plus version metadata
and release documentation. Native evidence uses Windows, KiCad 10.0.6,
Python 3.11.5 and wxPython 4.2.2. Functional evidence is recorded in the
[shared responsiveness audit](SUITE_RESPONSIVENESS_2026-10-23.md).

- Shared portable checks: 595 passed, 112 skipped and 464 subtests passed.
- Native Via Stitching/routing checks: 35 passed. Connected two-plane guard
  fixture: 22 through-vias, no new DRC findings and unchanged source bytes.
- Native Fanout checks: 14 passed, including Before/After, component thumbnails,
  small-window button bounds and Apply/Undo. The test harness owns its native
  event loop; repeated application-global loop re-entry is not a product path.
- Native source-identity checks: nine passed, including unsaved manufacturing
  floors. Saved Marble and its isolated worker snapshot have matching identities.
- Quick PI: 334 portable passes, 51 skips and 383 subtests; QuickTherm: 254
  portable passes, 28 skips and 196 subtests. Native checks are separate.
- Prior source packaging: 24 independent disposable PCM ZIPs passed validation;
  isolated routing ZIP workers reproduced the same 22 guard-via coordinates.

The release candidate must pass its exact-commit CI, package/document checks,
isolated-wheel and routing-payload smoke checks before publication. Existing
public feed descriptors stay unchanged until all new assets are uploaded and
downloaded hashes match the local release payloads. Native packages with no
source changes retain their existing versions and must match published bytes.

Assistant is included as a testing package. It coordinates supported local
CLI operations; it does not establish numerical or manufacturing qualification.
Connected-editor IPC and weaker-hardware performance remain unverified.

## Published asset checks

- All eight jobs passed for source commit `f08609a4` in
  [release CI](https://github.com/wayri/WayriCAD/actions/runs/39944660962).
- The release tag resolves to that exact source commit. All 31 uploaded assets
  have matching server digests; every public download was retrieved and its
  SHA-256 matched the validated local payload.
- All 24 candidate PCM ZIPs passed schemas, syntax, icons, entrypoints and
  download hashes. The six native ZIPs retain their published bytes and versions.
- The release wheel passed isolated CLI/report/assets smoke checks. The source
  archive contains 1,215 tracked files that match the release checkout exactly.
  An inspection of 26 archives found no validation caches or known private paths.
- Both final routing ZIP workers reproduced the 22 guard-via positions and
  board context without modifying their copied source. Release inventory and
  package checks passed seven tests / 24 subtests; CLI adapter checks passed
  11 tests / 216 subtests in their independent import context.

The public PCM descriptors are promoted separately from the tested release
source, after publication and download verification. Published binaries and
earlier tags are not replaced.
