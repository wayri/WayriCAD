# Fabrication Net Comparison

Compare a saved design-reference netlist with an independently extracted CAM
netlist. The native dialog is read-only: it neither edits the PCB nor reconstructs
copper from Gerber images. **MATCH is matching supplied endpoint partitions, not
physical fabrication verification or manufacturing release approval.**

## Native Workflow

1. Save the board. When opened with PCB context, **Export design reference...**
   runs the native helper asynchronously on a private saved-board copy. Choose
   a new `.d356` destination; it also writes a `.d356.receipt.json`. The result
   fills the reference picker. Both paths must be new. Obtain a design reference and a CAM-extracted netlist for the
   same revision. The native reference exporter uses KiCad's saved design; its
   receipt says `design-netlist`, not CAM extraction.
   A present native receipt is checked against the reference bytes and, when
   supplied, saved PCB bytes. Its own hash joins the guarded source snapshot.
   A missing receipt remains `UNVERIFIED`; showing PCB context alone does not
   claim correspondence to that board. Local hash binding is not authenticated
   CAM independence or fabrication evidence.
2. Open Fabrication Net Comparison from the manufacturing UI. Choose **Design
   reference** and **Observed CAM netlist** independently.
3. Check the independence confirmation only after reviewing the CAM producer and
   extraction basis. A filename or provenance claim is not proof of independence.
   Leaving it unchecked permits useful difference detection but cannot MATCH.
4. Compare. Review short/open **groups**, coverage and issues separately. Select
   any row to inspect its complete original net names and endpoint/pin mapping.
   Column sorting keeps the selected finding's identity attached to its details.
   The native table shows at most 5,000 rows and details show at most 500,000
   characters, with explicit truncation notices. Complete findings and pin maps
   remain in the canonical report and all exports; no evidence is discarded.
5. Export JSON, offline HTML, CSV or TXT. Source changes, changed form inputs,
   cancellation and failed reruns invalidate old results and export eligibility.
   Use the bundled HTML Help button for the installed workflow and limitations.

Only one worker runs per dialog. File paths and the confirmation boolean are
copied on the GUI thread; all loading/parsing/comparison uses plain data. Cancel
and input edits stop work between calls and discard late output. An active
parser/comparator call cannot currently be interrupted. Closing/destroying the
dialog cancels and prevents late native-control access. There is no KiCad board
object in the worker.

The native reference helper supports subprocess cancellation and a bounded
timeout. A new reference already published just before cancellation is retained,
not silently deleted; inspect the chosen destination. No observed CAM extraction
is inferred from the generated design reference.

## Interpretation

- **SHORT**: one observed CAM partition joins endpoints from multiple design
  partitions. The report retains every original design net and its member pins
  in one group; it does not manufacture an all-pairs error list.
- **OPEN**: one design partition is split into multiple observed partitions.
- **MISSING / EXTRA**: reference/observed endpoint coverage differs. These are
  coverage defects, separate from the number of proven short/open groups.
- **ISSUE**: parser, unsupported-format, ambiguous-identity or independence
  limitations. Inspect the full detail, not just the summary count.
- **FAIL**: at least one short/open is proven on shared accepted endpoints.
- **UNKNOWN**: no proven difference, but incomplete/unsupported coverage,
  unconfirmed independence, or identical source/normalized input prevents MATCH.
- **MATCH**: complete accepted partitions match, independence is explicitly
  confirmed, and self-comparison checks do not reject the inputs. The core still
  records `fabrication_verified: false`.

Connectivity is compared by exact case-sensitive `(reference, pin)` identities.
Net names are partition labels local to each file. A design `GND` is not joined
to some observed net merely because its name is also `GND`; renumbered observed
nets can match when their endpoint partitions match. Coordinates are not used to
guess missing identities. Disconnected `N/C`/null terminals remain isolated,
not a common global disconnected net.

## Supported Inputs And Limits

The current bounded core reads IPC-D-356 subset records 317/327/367 with explicit
ASCII CODE 00 and CUST 0 decimil units, or normalized UTF-8 JSON:

```json
{
  "schema": "wayricad.fab-netlist/v1",
  "units": "mm",
  "terminals": [
    {"reference": "J1", "pin": "1", "net": "CAM_168"},
    {"reference": "U1", "pin": "3", "net": "CAM_168"}
  ],
  "provenance": {"origin": "cam", "producer": "Reviewed extractor"}
}
```

This miniature JSON illustrates the format, not independent fabrication
evidence. Only the documented top-level and terminal fields are supported.
Optional coordinates require both `x_mm` and `y_mm`, in mm. Netlists are bounded
to 16 MiB and the core's record/tree budgets. Full-width/truncated reference,
pin or unaliased net identities cannot establish complete proofs. Unsupported
units/transforms/records, malformed terminals, unidentified vias and mechanical
features retain structured coverage/issue information rather than becoming
invented copper connections. No Gerber reconstruction, physical open/short
geometry checking, impedance qualification or CAM process certification is done.

## CLI Examples

Export a native design reference to a **new** path:

```text
python -m manufacturing_readiness_plugin.dfm_cli fab-reference C:/Projects/Example/controller.kicad_pcb C:/Projects/Example/review/controller-reference.d356
```

Compare against a separately reviewed CAM extract and export all formats:

```text
python -m manufacturing_readiness_plugin.dfm_cli fab-compare --reference C:/Projects/Example/review/controller-reference.d356 --cam C:/Projects/Example/cam/controller-observed.d356 --confirm-independent-cam --json C:/Projects/Example/review/net-compare.json --html C:/Projects/Example/review/net-compare.html --csv C:/Projects/Example/review/net-compare.csv --text C:/Projects/Example/review/net-compare.txt
```

Use the generic **synthetic** nine-design-net / single-CAM-group example:

```text
python -m manufacturing_readiness_plugin.dfm_cli fab-compare --reference manufacturing_readiness_plugin/examples/fab-reference.json --cam manufacturing_readiness_plugin/examples/fab-intentional-short.json --confirm-independent-cam --html C:/Projects/Example/review/synthetic-short.html --text C:/Projects/Example/review/synthetic-short.txt
```

That intentionally synthesized fixture has 18 pins and one observed net `168`
joining nine design nets: **one short group**, not 36 pairwise errors. It is
not extracted from fabricated copper and the confirmation flag cannot turn it
into manufacturing evidence. CLI codes are 0 for MATCH, 1 for FAIL, 3 for UNKNOWN,
2 for input/I/O errors and 130 for cancellation. None is physical fabrication
approval.

## Canonical Reports And Safety

The core's `wayricad.fab-compare/v1` verdict, source formats, original names,
groups, coverage, issues, independence and provenance remain intact. The report
layer adds `report_metadata` (`wayricad.fab-net-compare-report/v1`) with UTC
generation, selected/canonical paths, byte counts, exact SHA-256, saved mtime and
a report SHA-256. The report hash covers the canonical full report with only
its own hash field omitted; it detects accidental mutation, not authenticity.
Parsed-input hashes must match the selected file snapshots.

Exports recheck source identity and the report hash, protect both inputs and any
supplied PCB context/project files from overwrite, reject symbolic-link output
aliases, and use unique temporary files with rollback on publication failure.
JSON retains exact structured evidence. HTML escapes every input-derived value
and has no script/network capability. CSV prefixes spreadsheet formula-triggering
cells with an apostrophe; JSON retains the unmodified original values. TXT is a
compact grouped engineering report rather than a raw JSON dump.

Inputs can contain proprietary nets/pins and local source paths. Reports are
local artifacts, not automatically sanitized for public sharing.

## Module API And Checks

`fab_compare_report` exposes `source_snapshot(path, role)`,
`assert_sources_current(sources)`, `build_report(comparison, *, sources,
board_path=None)`, `validate_report(report)`, `report_rows(report)`,
`render_report(report, format)` and `export_report(report, destination,
format=None, protected_sources=())`. Source roles should be `reference` and
`observed CAM`; an optional board context can be fingerprinted separately.
Rendering accepts leading-dot extensions as well as plain format names.

The native entry point is `fab_compare_ui.open_dialog(parent,
reference_path=None, board_path=None)`. The board path is context/protection, not
an implicit observed CAM extraction.

```text
python -m unittest discover -s manufacturing_readiness_plugin/tests -p test_fab_compare_report.py -v
python -m unittest discover -s manufacturing_readiness_plugin/tests -p test_fab_compare_ui.py -v
```

Run suites separately. UI checks need native wxPython; skipped native tests are
not passes. Core, report safety, native UI behavior and actual CAM producer
qualification are separate evidence.
