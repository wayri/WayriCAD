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
