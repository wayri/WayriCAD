# Running and interpreting native acceptance

## Scope and status

The delivered container has no KiCad, `pcbnew` or wxPython. Package-manager
installation attempts were blocked by DNS/network access. The recorded run
therefore executes core checks and marks native work SKIP. It is not evidence
of a working Windows GUI or native DRC implementation.

`constraint_studio.acceptance` is the same runner in PCM and source installations.
It creates its own board fixtures in a NEW/EMPTY evidence folder, records source
hashes and environment, and never edits user design files.

## Windows

Extract the source ZIP. Double-click `Run Acceptance.cmd`, or pass the exact
KiCad-compatible Python interpreter:

```bat
"Run Acceptance.cmd" "C:\Program Files\KiCad\10.0\bin\python.exe"
```

The conventional path is only a discovery candidate, not a claim that every
installation uses it. Alternatively, from that interpreter's environment:

```text
python -m constraint_studio.acceptance --gui --output C:\CS-Acceptance-NEW
```

Add `--cli FULL_PATH_TO_KICAD_CLI` when CLI discovery fails. Native CLI tests
require version 10.x. PCB and wx tests must use the actual KiCad Python ABI;
installing ordinary unrelated Python is not equivalent.

## Outputs and result meanings

- `acceptance.json`: environment, code hashes, test status/detail/tracebacks.
- `ACCEPTANCE_REPORT.md`: readable inventory of PASS, FAIL, SKIP, MANUAL_REQUIRED.
- Native CLI logs/report JSON and disposable native geometry fixtures when run.
- Actual desktop screenshots from the GUI sweep when wx/display are available.

Exit 0 is reserved for a complete gate, exit 1 denotes an actual test failure,
and exit 2 denotes incomplete work. This version intentionally includes manual
checks that are not auto-promoted. A green compiler run cannot hide them.

The native CLI sweep activates all 34 catalog forms individually. A deliberately
invalid constraint is a negative control. A report/exit code proves parsing and
execution on that fixture, not that every geometric rule semantics is correct.
Violations may be intentional; semantic and boundary checks remain required.

The PCB API checks exercise load/save, footprint-owned areas, move/rotate/flip,
and curved/nested contour serialization. Those API checks are distinct from
interactive PCB Editor operations and library updates.

## Hands-on acceptance still required

Record exact KiCad build, OS, plugin ZIP SHA-256, display resolution and actual
Windows scale. Test at 100%, 125%, 150%, 200%; do not emulate these merely by
resizing a window. Inspect all pages/dialogs, scroll ranges, keyboard focus,
clipboard, validation errors, undo/redo, and long names.

Verify native BGA pair clearances entirely inside, inside/outside, on a boundary,
crossing a boundary, inside a hole, and on different islands. Test non-symmetric
front and back courtyards, actual native move/rotate/flip, footprint duplication,
reference changes, library replacement and saved courtyard edits. An independent
edit to a managed area/rule must be refused, not overwritten.

Compare the offline trace to native resolution for same-net checks, local pad
clearances, composite classes, layer conditions, fromTo connectivity and global
minima. An unsupported offline case must stay UNKNOWN.

Verify native A/B selection, cross-probe/focus, stale-board rejection, DRC item
UUIDs, stale report labeling, review export, closed-project checks and backups.
Complete signed review with a separately verified public-key registry and an
external protected head anchor; repeat after a content edit and after tampering.

A reviewer should record each manual outcome against the package hash and attach
screenshots/logs. Do not replace SKIP with PASS by editing the machine report.
The full earlier detailed checklist remains in NATIVE_ACCEPTANCE_CHECKLIST.md.
