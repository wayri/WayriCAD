# WayriCAD 4.2.0 validation scope

This release adds DFM/DFA checklists, whole-board/bundle RLC sections and PI series
power-tree output while retaining the existing manufacturing manager. See the
[release notes](../RELEASE_NOTES_4.2.0.md) for supported scope and limitations.

## Local checks

Windows, KiCad 10.0.6 and cached KiCad Python 3.11 were used for native saved-file
and hidden-controller checks. Stock Python 3.14 ran the portable source checks.
No local dependency installation was performed for this release.

| Check | Result |
|---|---|
| Manufacturing and presentation source checks | 78 passed, 13 skipped, 64 subtests passed |
| Native DFM controller checks | 12 passed, no skips |
| PI tree export/source-preservation regressions | 14 passed |
| Thermal multilayer regressions | 22 passed |
| SI saved-worker regressions | 10 passed |
| PI report/tree/result-overview checks | 21 passed, 1 skipped, 9 subtests passed |
| RLC focused checks | 22 passed |
| PCM validation | 26 independent archives passed schemas, syntax, icons, entrypoints and hashes |
| Source documentation validation | Passed |

These groups overlap and are not a combined test count. The complete CI matrix
also runs the remaining repository/plugin tests and clean distribution builds.
The release provenance records its exact source commit and CI run; the wheel and
source distribution and published PCM archives are taken from the validated CI
build so their exact bytes match the tested checkout.

Native known-answer negative fixtures proved that ignored project check providers
could suppress custom rules. The corrected private vendor snapshot retains named
failures for track width, clearance, hole size, annular ring and edge clearance.
Original PCB/project/custom-rule bytes remained unchanged. Microvia, shorting and
crossing provider names were checked against native project settings; those
specific geometry branches were not separately exercised.

Native DFM export API checks retained every requirement and produced approximately
41 kB HTML, 69 kB PDF and 34 kB JSON for a synthetic fixture. RLC export API checks
retained all three fixture nets and 20 current-carrying pins. These are saved-file
and API checks, not visible editor interactions.

## Remaining acceptance work

Actual PCB-editor acceptance of the full PI series run, setup/simulation
save/reload, both export dialogs, power-tree/return-path screenshots and live IPC
cross-probing is pending. Hidden controller tests mock the IPC transport boundary.
KiCad 11 native acceptance is pending. No broad 3D solver speedup or complete
manufacturer/assembly qualification is claimed.

The initial catalogue has 21 process presets, of which 20 have native rules, and
28 directory entries. Unknown, manual and waived requirements do not become
automatic passes. Same-net fabrication gaps, coupled bundle extraction and
unsupported geometry retain their documented limits.
