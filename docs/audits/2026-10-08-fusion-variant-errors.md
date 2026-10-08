# Fusion and Variant Manager error recovery

Windows; KiCad 10.0.6 bundled Python 3.11.5. Generated fixtures only.
Fusion source Python 3.14 portable suite: 256 completed, 79 opt-in skips,
zero failures. Native failure tests: 5 passed. Native guided flow: 3 passed.
Variant Manager native service/UI suite: 12 passed. Shared suite: 336 passed,
77 skipped, 150 subtests passed. CLI contracts: 13 passed. All 19 disposable
PCM ZIPs passed independent schema, runtime/action, icon and syntax checks.

Regression checks cover retained staged batches, stale-source rejection,
failed exports, superseded callbacks and destroyed windows. Fusion invalidates
old Apply/open/handoff state after failure, preserves source inputs and repair
choices, and shows the latest validation failure with a recovery step.
Existing backend source hashes, lock checks, backup and rollback contracts remain.
No new geometry or solver behavior is introduced. Linux/macOS native UI checks
were not run. These source versions are pending a new public package release;
published 3.6.9 assets and PCM feed remain unchanged.
