# 3.6.37: Bulk Label Editor loading and workflow repair

## Failures and corrections

The stable PCB action inventoried references, values, fields and drawing text,
but never requested nets. Its prefilled CH*_MAIN rule hid every other string.
Under IPC, drawing objects all had Python type Item, which the old text-scope
allowlist excluded even after successfully reading their text.

The corrected action separately inventories fresh PCB nets and semantic text
rows. Empty Find browses text without arming Apply. Nets have member counts,
terminal names and UUIDs; they are never passed to a generic text setter.
Native NETINFO_ITEM.SetNetname alone was rejected as a shortcut: it changes the
object name but leaves stale keys in the board net-name lookup. Electrical
renaming remains a schematic-source operation.

Selected-footprint scope uses ownership UUIDs. Selection compares UUIDs rather
than transient Python wrappers; native graphical children, fields and groups
are included when clearing selection. IPC uses bulk net queries and checked
bulk selection with restoration on failure. Text writes are followed by new
board reads, rather than accepting the locally mutated proto as proof.

## Local native evidence

Windows; KiCad 10.0.6; bundled Python 3.11.5 and wxPython 4.2.2. Synthetic native
window tests cover initial text/net inventory, rename/Undo/Redo, protected
positions/pad counts/net membership, net search and exclusive selection,
sorted selected-row apply, narrow-window sizing, duplicate-reference ownership,
footprint text/group selection, saved-board CLI/source immutability, and the
real IPC facade with controlled API responses.

Marble public-board fixture was read without applying or saving edits:

| Measurement | Result |
|---|---:|
| Named nets | 1,374 |
| Text fields, all scopes | 35,765 |
| Native board load | 2.437 s |
| First window and complete inventories, after board load | 0.538 s |
| Wildcard search, 80 clock nets | 2.731 ms |

Single-run local measurements exclude interpreter/module startup and are not cross-hardware guarantees. Source SHA-256
stayed 482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0.
No user project was changed.

## Evidence boundaries

Native saved-board/wx tests and controlled IPC responses do not establish a
connected live-editor transaction on every platform. A connected editor was not
used for acceptance. Existing screenshots are retained and labelled as earlier
captures. New PrintWindow capture attempts returned uniform white pixels and
were rejected; no blank image was represented as a new screenshot.

## Automated and package acceptance

Portable tests cover collections/counts, live-name refresh, read failures,
wildcard/regex captures, reference collisions, stale batches, write failures,
recovery and CLI compatibility. Final checks and publication hashes follow.

### Completed local checks

- Focused plugin, CLI, UI and version contracts: 37 tests and 102 subtests passed.
- Native synthetic-board/window workflow: nine tests passed, none skipped.
- Independent final Bulk Label Editor PCM ZIP: the same nine native tests passed
  in a fresh process. Tests were staged externally; production modules and shared
  runtime loaded from the extracted installer, with source-byte checks.
- Required shared unittest discovery: 612 tests, no failures/errors, 124 skipped
  for unavailable optional/native workflows. Skips are not acceptance passes.
- All 24 PCM ZIPs passed schema, payload syntax, action/runtime, icon and SHA-256
  validation. Source and packaged documentation/images validated.

The tool remains modeless; native file/export pickers may be modal. The shared
modeless-window test now checks launcher Run methods rather than forbidding
file-dialog calls anywhere in a source file. The window stays interactive during
normal table search. No local plugin installation was performed.

## Publication

Published [3.6.37](https://github.com/wayri/WayriCAD/releases/tag/v3.6.37)
from `48bc0cfb197e6b46d0c2e1d24ddfde5d16807e04`. All eight
[exact-source CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40467686045)
passed across the configured Linux, Windows and macOS matrix and PI references.

The wheel passed isolated CLI/report/mechanical smoke checks, contains no tests
or bytecode, and its Bulk Label Editor modules match source. The source archive
has 1,352 tracked members matching the tested checkout, including the native
regressions. All 31 uploaded assets were downloaded and compared to local
SHA-256 hashes. Public Bulk Label Editor and feed URLs were checked afterward;
the PCM feed uses those exact released metadata bytes. Existing release assets
and tags were preserved. No local plugin installation was made.
