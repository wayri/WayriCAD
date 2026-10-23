# WayriCAD 3.6.30 release validation

Windows source and native checks use KiCad 10.0.6, Python 3.11.5 and wxPython
4.2.2. The system source-test runtime is Python 3.14. Original public boards
and derived trial inputs were preserved; no private user project was edited.

See [Fanout geometry, timing and native evidence](FANOUT_DENSE_BOARD_FIXES_2026-10-23.md)
for exact scopes, inherited findings, unfinished routing and limitations.
The affected native matrix covers 96 tests. Source worker/UI contracts cover
18 passes, six subtest passes and 14 native-only skips. Documentation, package
and isolated-distribution checks are recorded with publication verification.

All 24 package versions are advanced so independently installed tools receive
the updated shared runtime. Candidate PCM descriptors remain unpublished until
the release assets pass verification. Previously published binaries are retained.

## Published verification

- All eight [CI jobs](https://github.com/wayri/WayriCAD/actions/runs/39965813396)
  passed for source commit `d0f8b80b`. The release tag identifies that commit.
- All 31 public assets were downloaded and matched locally validated SHA-256
  hashes before public PCM feed promotion. All 24 ZIPs passed schemas, payload
  syntax, icons, entrypoints and feed hashes. Full documentation validation
  and 26 release-contract tests / 24 subtests passed.
- The wheel passed isolated CLI, report/assets and local-server checks.
  Inspection covered 26 archives / 5,756 files without validation caches or
  known private paths; 1,235 tracked source-archive members match the checkout.
- The extracted Fanout ZIP passed ten focused native checks and reproduced
  the exact 290-escape Marble geometry already accepted by native refill/DRC,
  without importing sibling/source packages. The full affected source native
  matrix passed 96 tests. This does not claim installed live-editor interaction
  or complete board routing.

Existing release tags and binaries remain unchanged. PCM feed promotion follows
publication and public-download verification as a separate maintainer commit.
