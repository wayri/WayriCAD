# Trace Refiner validation

Historical 0.1.x evidence. See [0.2.0 improvements and validation](TRACE_REFINER_0.2.0.md) for the current source candidate.

## Scope and environment

2026-10-15, Windows, KiCad 10.0.6 native Python 3.11. Trace Refiner 0.1.0 is a new native ActionPlugin candidate. Source and independently extracted PCM checks are distinct from an installed plugin being launched inside PCB Editor; the latter is not claimed here. Linux/macOS GUI and KiCad 11 are unverified.

## Checks

- 28 plugin tests passed with native process exit code zero: 11 pure geometry cases plus native scopes, topology/contact preservation, differential/protected routing, DRC approval/rejection, live rule/disk staleness, bus-name literal selection, partial-write recovery, post-write fingerprint failure recovery and the wx Preview/Validate/Apply/Undo flow.
- Geometry uses mm before conversion to native IU. The complete rounded candidate is rechecked against bidirectional centreline deviation and total shortening bounds. This is geometric screening, not timing or signal-integrity qualification.
- Native connectivity uses transitive connected-item sets once per component, avoiding repeated traversal of large ground nets. Pad/via/zone terminal components must be unchanged.
- Production validation runs in a disposable native Python process. A failed, cancelled, timed-out or crashed worker cannot enable Apply. Native project globals have process-lifetime ownership; a closed result file is written before the disposable worker exits without SWIG shutdown finalizers.
- Core copper checks are enabled in disposable project copies. A test with clearance disabled in the original saved project still rejects a new candidate clearance violation and verifies original project bytes are unchanged. Live scalar geometry rules and net classes, including pad/zone-only nets, are checked against saved project context. Save Board Setup before validation; unexposed live SWIG settings are not represented as fully serialized project state.
- 425 shared root tests passed, 87 explicitly skipped, with 170 subtests. Focused inventory/UX/CLI checks passed as well.
- KiCad emitted retired-track SWIG ownership warnings on isolated-process shutdown; the process exited successfully. Long-running repeated-session memory use is not qualified.
- Candidate PCM validation covers all 21 source plugins: official metadata schemas, independent runtime, action entrypoints, icon sizes and Python syntax. Source documentation and local image links passed validation.
- An extracted Trace Refiner PCM ZIP was imported with source paths excluded. Native Preview, worker/DRC, Apply/Undo/Redo and window construction passed without sibling runtime imports. The screenshot is a real wx window using a disposable routing fixture and contains no project paths.

## Public board evidence and limits

The saved [Marble revision](https://github.com/BerkeleyLab/Marble/tree/a426777d92c0f22a546d4740b419a3937e0c1f90/design) contains 41,044 routed items. Final preview produced 259 candidate chains and 339 explicit preservation notices in about 13.91 seconds. Live serialization and PCB/project file hashes were unchanged. Counts exclude protected or otherwise ineligible routing; notices are not a count of every skipped track.

A one-chain candidate was separately checked with complete before/after CLI runs and zone refill. Both reports contained 2,083 violations and four unconnected findings, including many existing dimension/clearance failures. Despite equal totals, reported identity sets differed on unrelated routing. No candidate was applied. These results prompted a conservative gate: a baseline with 199 or more findings of any one type is rejected before candidate approval. This does not establish that every report below that policy threshold is globally complete; native report limits and the exact KiCad version remain relevant.

Marble demonstrates preview scale and a safe rejection, not a validated edit or a clean board. Resolve an excessive baseline before applying refinement. The planner is bounded local jog cleanup, not obstacle shoving, differential-pair retuning or whole-board routing optimization. Explicit net protection and final native DRC after zone refill remain required.

## API references

Native API assumptions were checked against the installed bindings and KiCad 10 source: [board settings](https://gitlab.com/kicad/code/kicad/-/blob/10.0/pcbnew/board_design_settings.cpp), [DRC codes](https://gitlab.com/kicad/code/kicad/-/blob/10.0/pcbnew/drc/drc_item.h), and [project manager lifetime](https://gitlab.com/kicad/code/kicad/-/blob/10.0/common/settings/settings_manager.cpp). No severity enum pointer is treated as an integer value: the SWIG binding does not expose that value safely.

## Release 3.6.18 CLI and documentation

The command-line entry point is `wayricad-trace-refiner`; the source module is
`python -m trace_refiner_plugin`. It handles saved projects only. A native child
owns project lifetimes; analysis failures leave output files unwritten.

Five CLI tests passed on Windows / KiCad 10.0.6 / Python 3.11: portable help,
exact-net/netclass/UUID scoping and invalid selectors, validated export with
source/project SHA-256 custody and no-overwrite, missing-project rejection,
and a native copper-clearance failure that leaves no output PCB/project.
The existing 28 geometry/native/UI tests also passed. Focused shared CLI,
inventory and UX checks passed: 29 tests and 93 subtests.

Offline Help and README now explain bounds, protected routing, saved settings,
CLI arguments and JSON statuses, export review, and failure remedies. The native
fixture screenshot and independent icon are retained. PCM installation exposes
the native action; the wheel exposes the console entry point. Installing a PCM
ZIP alone does not install a global shell command.

An independently extracted 0.1.0 PCM archive also passed CLI exact-net selection,
native worker connectivity/DRC and export to a new PCB/project with source-tree
imports excluded. All 21 candidate ZIPs passed schema, entrypoint, icon and
payload checks. Source documentation and local illustrations passed validation.
