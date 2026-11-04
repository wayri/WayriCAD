# Saved-board analysis across KiCad versions

Quick PI, QuickTherm, Quick SI, Trace RLC and DFM/DFA Studio use native KiCad 10
geometry for read-only saved-board analysis. KiCad 10 files retain their direct
native load path. A KiCad 10 native Python runtime is still required; a KiCad
11-only installation is not supported by this adapter.

For a PCB saved in KiCad 11's development format, the launcher obtains the CLI
path from its authenticated originating editor. It converts a private copy with
an actual strict `pcb downgrade --target 10.0` export. The original PCB, project
and custom rules are never overwritten. Standalone analysis can select the
matching newer CLI explicitly through `KICAD_CLI`. The helper's adjacent KiCad 10
CLI and unrelated editors are not fallbacks.

Conversion refuses features that the native CLI cannot preserve. It never uses
`--force`, `--drop-approximations` or variant flattening. Dry-run success is not
conversion acceptance. Project text-variable values containing `${…}` references
or `@{…}` expressions are also refused: the development CLI's project-dependent
classification cannot yet establish their lossless conversion to the older
format. These boards require a matching native backend.

Reports and setup/result files retain the original board identity. Converted
results additionally record original board/project/rule fingerprints, converter
version and executable hash, derived board hash and target format. Source changes
invalidate reuse; historical results remain inspectable but cannot be restored
as current. Temporary boards remain alive with their native consumers. Workers
own conversion scratch and contain converter descendants during cancellation.

This adapter does not establish editing, native DRC or whole-project equivalence.
DFM/DFA Studio uses the original saved board and originating host's CLI for
native DRC; converted geometry supplies the local preview. Other plugins and
PCB-writing workflows are outside this adapter.

## Validation scope

Windows saved-file checks used KiCad 10.0.6 native Python and development CLI
10.99.0 (`10.99.0.6258.gff9515f1e9`, PCB format `20261031`). A full
VIN → MID → OUT path with Q1∥Q2 and Q3∥Q4 retained three copper domains, both
parallel banks and all twenty current-carrying pins. At a 0.5 mm mesh setting,
both input formats produced the same 0.27608709035504914 V drop at 3.3 V / 2 A.
A filled return-plane fixture retained its native geometry fingerprint.
Native negative fixtures rejected non-component pads and footprint height.

These are backend checks, not complete editor acceptance. Actual inference,
value entry, save/reload and export dialogs remain separate checks. The 10.99
build is a development build, not released KiCad 11.0. No native Linux/macOS
editor compatibility is implied.
