# Portable saved results for Pocket KiView

`wayricad_runtime.pocket_kivi_export` prepares existing result data for the
read-only Pocket KiView saved-analysis viewer. It does not run a solver, change a
design, derive missing samples or convert coordinate systems. Producer entry
points must call it explicitly; adding this helper alone does not add an export
button or CLI option to a tool.

The viewer identifies supported results by their saved structures. Keep Quick PI
`mesh` and `result` at the root. QuickTherm grids, active-cell spatial indexing,
layer-major transient frames and Quick SI eye/step structures retain their
original placement. Unsupported shapes remain inspectable JSON rather than
acquiring invented plots or geometry.

## Save from the tools

[Actual same-PCB PI, SI and thermal examples](examples/pocket-kivi/README.md)
include the source PCB, complete portable outputs and a reproducible generator.

Quick PI and QuickTherm **Save results** write the readable HTML report, the
complete original numerical JSON, and a `.pocket-kivi.json` companion. Quick SI
**Save results / Pocket KiVi** does the same for saved-board analyses. Its live
editor results still save complete HTML/JSON, but have no verified saved-PCB
binding. Rerun the saved-board analysis to obtain that binding. PI batch exports
include a separate complete portable file for each successful case.

Mechanical Check includes the companion for a saved single-board scene. Live
snapshots and multi-board scenes retain their original full JSON; they do not
claim a single verified PCB coordinate registration. Mechanical mesh coordinates
remain scene coordinates.

Open a portable companion alongside its matching saved PCB in Pocket KiView.
Copying an export does not include the PCB itself. Keep original full JSON for
reproduction and further analysis. A report cannot make unsupported solver
geometry or unavailable results valid.

## Command line

Existing solver CLI JSON remains supported. Convert a complete saved result with
the hash recorded when it was solved:

```text
wayricad-pocket-export result.json portable.json --board board.kicad_pcb --source-sha256 <solve-time-sha256> --tool "Quick PI" --version <producer-version> --saved-source
```

The module form is `python -m wayricad_runtime.pocket_kivi_cli`. Supply a new
destination and the actual producer version. The saved-source confirmation is
required; computing a fresh PCB hash cannot establish that an older result came
from those bytes. The command rejects duplicate JSON fields, nonfinite numbers,
stale source files and oversized input. Units and coordinate conventions remain
unknown unless already established by producer data; the generic command does
not infer them.

## Producer API

```python
from wayricad_runtime.pocket_kivi_export import (
    portable_bundle, portable_json, export_bundle,
)

# Retained when this completed analysis loaded its saved board, not computed
# now to make an older result appear current.
evidence = dict(
    board_path="C:/Projects/Example/board.kicad_pcb",
    source_sha256=solve_time_saved_pcb_sha256,
    source_state="saved",
    tool="Quick PI",
    version=producer_version,
    source_root="C:/Projects/Example",
    units={"potential_V": "V", "cell_power_W": "W"},
    coordinate_frame="KiCad PCB XY in mm",
    z_basis="front-depth",
)

copy = portable_bundle(completed_result_bundle, **evidence)
utf8_json = portable_json(completed_result_bundle, **evidence)
receipt = export_bundle(completed_result_bundle, new_json_path, **evidence)
```

Choose one operation for the intended destination. `portable_bundle` returns an
independent JSON-compatible copy. `portable_json` returns strict UTF-8 JSON bytes,
including a final newline. `export_bundle` publishes a new `.json` file with the
shared report staging/source-protection contract and returns its path, byte count,
file SHA-256 and source SHA-256. Existing files, including old exports, are
protected: choose a new destination. Rendering/verification of native reports and
producer-specific release checks remain separate workflows.

Only declare units, coordinate frame and elevation convention supported by the
actual producer data. These optional arguments default to `None`, which is
written as explicit JSON `null`. The helper never assumes PCB axes, invents
layer elevations, flips Z, adds board outlines, or gives SI curves spatial
coordinates. For example, Quick PI's documented positive-depth convention can
support `front-depth`; a mechanical scene in its own coordinates cannot inherit
that convention simply because a PCB was supplied.

## Saved-source custody

`board_path`, `source_sha256`, `tool`, `version` and `source_state` are required.
The source must be a saved `.kicad_pcb`, and `source_state` must explicitly be
`saved`. The SHA-256 is the hash of its exact solve-time bytes, including original
line endings. Disk bytes must still match before and after conversion, and
before and after file publication. A conflicting existing board binding is an
error; an old result is never silently rebound to a current board.

The caller remains responsible for establishing that the analysis actually
loaded those saved bytes. A file hash cannot prove that a live KiCad object has
no unsaved changes. Do not expose this saved-board export for live/unsaved Quick
SI results. Reopen and rerun through the saved-board worker first. Explicit
live/unsaved flags in the supplied bundle are rejected as an additional guard.

Named `study_sha256`, `study_file_sha256`, `geometry_sha256`, `source_hash` and
model hashes keep their original meanings; they cannot substitute for the PCB
digest. Existing source and study-file contracts use the shared
`report_ui.checked_sources` check. Nested `source_fingerprints` maps also verify
project/rule files and retain recorded absence as `null`; a newly appearing
previously absent file invalidates the export. This helper handles one saved
PCB: a nested declaration of another PCB requires a separate export instead of
an ambiguous primary binding.

The helper adds the viewer-recognized root `source_path` and `source_sha256`
pair. Additional metadata lives under `pocket_kivi_export`, with schema
`wayricad.pocket-kivi-export/v1`, actual producer tool/version, saved-source
state, units, coordinate frame and `zBasis`. Existing producer schemas and all
other result fields remain intact. Export the original producer bundle, rather
than re-exporting a portable copy whose source paths were already relocated.

## Portability and bounds

Recognized filesystem fields (`source_path`, `board_path`, request paths,
`*_path`, `*_file`, directories and their plural forms) become safe relative
paths. Paths inside `source_root` retain their project-relative spelling; the
default root is the PCB directory. External files retain their basename under
`_external/<stable-path-alias>/`, preventing absolute private directory names
and same-basename collisions. Path-keyed `source_fingerprints` maps use the same
relocation. A relative path is metadata, not an included file: the exporter does
not copy board, project, model or study files. Public provenance URLs remain
URLs.

Net names, signal names, dictionary keys and object IDs are not interpreted as
filesystem paths. Hierarchical nets such as `/Front outputs/SLOT1` therefore
remain exact. Free-form comments and other non-path text are preserved; this
helper is not a general personal-information redactor.

Arrays, sample order, repeated event times, numeric values and explicit `null`
gaps are preserved. Nonfinite numbers, circular objects, non-JSON values and
non-string object keys are rejected instead of coerced. Output is bounded to
64 MiB of strict JSON, including metadata and its final newline, and 64 nesting
levels. Viewer-specific row, surface and plot budgets still apply independently.

Import the corresponding PCB alongside the report to use the viewer's exact
SHA-256 source match. A matching source does not establish model applicability
or solver accuracy. The viewer uses supported producer fields for placement;
adding descriptive metadata alone does not extend its rendering adapters.

## Validation

Run focused tests with a fresh workspace temporary directory:

```text
python -m pytest tests/test_pocket_kivi_export.py --basetemp .validation/pocket-kivi-pytest -q
```

Tests cover preserved PI/thermal/SI structures, exact names/IDs, null and event
gaps, path relocation, saved-file and settings custody, stale/conflicting hashes,
strict JSON/size bounds, source changes during conversion/publication and source
overwrite rejection. These are export-contract checks, not numerical solver or
live-editor compatibility evidence.
