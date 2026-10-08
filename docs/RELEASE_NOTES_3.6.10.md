# WayriCAD 3.6.10

This release includes independently installable Project Fusion 0.9.8 and
Variant Manager 0.6.1. Refresh the WayriCAD PCM repository, update both packages
and restart KiCad, or install either PCM ZIP from this release.

Fusion clears stale candidate and Apply state after a failed preview/apply while
retaining sources, settings and repair choices. Its Issues panel shows the latest
failure with recovery guidance. Import/subsheet error dialogs have selectable
details and a Copy details action. Background completions are ignored after
window destruction. The CLI rejects an existing result path before writes; exit
code 3 explicitly reports a completed operation whose result export failed.

Variant Manager retains the earlier staged batch after an ordinary staging error.
Stale inputs or failed Apply block further Apply until reload and review. Failed
reload clears old inventory; project changes and Clear invalidate older worker
results. Restore and ordinary staging cannot silently replace one another.
Failed report exports retain the review and provide a retry message.

Windows/KiCad 10.0.6 native validation: five Fusion failure/recovery checks,
three guided-flow checks, and twelve Variant Manager service/native UI checks.
Portable Fusion suite: 256 completed, 79 opt-in skips, zero failures. Shared
suite: 336 passed, 77 skipped, 150 subtests passed. Independent PCM schemas,
actions, icons and syntax validated. See the
[validation record](audits/2026-10-08-fusion-variant-errors.md).

Backup, lock and source-hash contracts remain active. Fusion named footprint
substitutions and automatic linked updates of named imported configurations
remain restricted. Linux/macOS native UI qualification is unverified. Other
packages retain their existing published versions.
