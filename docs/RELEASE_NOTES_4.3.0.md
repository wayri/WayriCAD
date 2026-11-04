# WayriCAD 4.3.0

This release adds in-editor Quick PI series-path review, named batch setups,
path diagrams, experimental read-only analysis of newer saved boards, and
schematic pin attraction for Component Arranger. KiCad 10.0.6 remains the native
validation target. Local tests, package validation, documentation checks and
isolated wheel checks passed; native editor coverage remains fixture-specific
and partial.

## Quick PI series studies

- **Auto infer path** shows saved-net route candidates inside the series editor.
  Review every current-carrying pin, excluded control pin, parallel component
  and explicit R/L or forward-drop model before using a path. Discovery does
  not establish device state or copper continuity; the solve checks the latter.
- The editor retains incomplete inference and path drafts while Quick PI stays
  open. Named batch setups keep each reviewed path, exact pad groups, voltage
  and prescribed current independently. Save/load and run use the existing
  versioned setup and batch contracts with board-revision checks.
- A schematic series/parallel diagram shows every stage and branch. The power
  tree reports solved voltage, current and loss where available. Saved planar
  track/arc endpoint chains provide routed-length evidence; straight-line
  estimates are labelled separately. Zones, pad interiors and via barrels do
  not receive invented wire lengths. Diagram SVG export protects source files.
- Batch results provide case summaries and links to individual electrical
  reports. Reports retain the full topology and numerical evidence. Independent
  prescribed-current cases do not imply shared regulation, AC coupling or a
  solved return loop.

## Newer saved-board analysis, with strict limits

Quick PI, QuickTherm, Quick SI, Trace RLC and DFM/DFA Studio can inspect a
KiCad 11 development-format saved PCB through a private, strict downgrade
snapshot. The original PCB, project and custom rules are not overwritten.
Results retain source, project/rule and converter fingerprints; stale inputs
invalidate reuse. Analysis workers contain their converter children on
cancellation. DFM native DRC uses the originating host's CLI and original
board, while the converted snapshot supplies its local preview.

KiCad 10 files continue through their direct native load path. Newer-format
analysis still requires a native KiCad 10 Python backend and the originating
newer editor's `kicad-cli`; standalone callers may explicitly select the
matching CLI. Unsupported or potentially lossy conversion is refused. This
adapter is for read-only analysis, not KiCad 11 editing, native DRC equivalence
or whole-project conversion. The recorded newer-host check used development
build `10.99.0.6258.gff9515f1e9` (commit `ff9515f1e9`), not a released KiCad
11.0 build. [Adapter scope and evidence](SAVED_BOARD_ANALYSIS.md).

## Component Arranger pin attraction

Component Arranger 0.1.18 adds optional, bounded schematic pin springs to its
placement proposal. Drawn-wire paths are matched to exact schematic
occurrences and same-net PCB pads; ambiguous mappings add no spring. The
strength control and preview metrics expose the effect. Existing fixed-part,
candidate and native DRC gates still govern Apply. The spring score is a
placement hint, not routing closure or proof of a completed electrical net.

## Validation status

On Windows with **KiCad 10.0.6**, the actual PCB Editor completed a
VIN → MID → OUT run with Q1∥Q2, Q3∥Q4, three nets, two banks and all 20
current-carrying pins; four control pins were excluded. Setup and simulation
save/reload, HTML and PDF export, compact diagram inspection and SVG export
were exercised. This is fixture-specific editor evidence, not a full-suite
acceptance claim.

On Windows with development build **10.99.0.6258.gff9515f1e9**, the editor
saved the newer PCB format (`20261031`) and Quick PI exercised inline
inference, explicit models, a full path run, setup save/reload and HTML export.
PDF, diagram and screenshot checks on that host remain pending after the
desktop session was interrupted. The complete KiCad 11 suite and Linux/macOS
native editors have not been qualified. See the [compatibility record](COMPATIBILITY.md#43-candidate-editor-evidence)
for the exact scope of these checks.
