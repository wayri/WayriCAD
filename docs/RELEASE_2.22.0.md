# KiWay v2.22.0

KiWay v2.22.0 expands the suite to 15 independently installable KiCad 10
packages and standardizes their PCM and PCB Editor presentation.

## New engineering workbenches

- **Return-Path Auditor** screens routed geometry for reference-plane,
  transition-via, branch/stub, and differential-coupling risks.
- **Harness and Cable Workbench** imports board pin documents, links endpoints
  with exact/wildcard/regex rules, checks conflicts, and exports wire lists and
  harness diagrams.
- **Manufacturing Readiness Manager** combines fabricator profiles, board and
  DRC checks, KiCad jobsets, explicit release gates, and deterministic release
  archives.
- **PDN and Decoupling Planner** reviews rail/load/capacitor relationships and
  flags power pins without nearby rail-to-ground decoupling.
- **Protocol Constraint Composer** detects common interface nets and generates
  a reviewable, backed-up KiCad custom-rule block.

## Pin Extractor

The new **Programming & Bring-Up** workflow identifies SWD, JTAG, UART, reset,
boot-strap, reference-voltage, supply, and ground connections. The reviewed
result can be exported as Markdown or C definitions for firmware and lab use.

## Packaging and interface consistency

- All 15 packages have unique, lightweight 96 x 96 source icons.
- PCM archives contain a normalized 64 x 64 `resources/icon.png`.
- ActionPlugin launchers provide both light- and dark-theme icon paths.
- Package metadata uses KiCad-supported `swig`/`ipc` runtime values and direct
  icon URLs from the `develop` branch.
- Guided workflows, integrated HTML help, staged previews, and engineering
  limitations are included in the five new workbenches.

## Feed migration

Connector ICD Builder, Net Hygiene, and Test Coverage Planner are retired from
the PCM feed. Their retained capabilities are consolidated into Pin Extractor,
Test Point Descriptor Extractor, Harness and Cable Workbench, and the newer
audit tools. Remove/re-add the repository URL if KiCad displays a cached entry:

`https://raw.githubusercontent.com/wayri/KiWay/develop/pcm/repo.json`

## Validation

The release is covered by repository unit tests, package archive inspection,
KiCad-bundled Python compilation, icon dimension checks, and PCM feed schema
guards. Engineering estimates and generated rules remain review aids and do
not replace ERC, DRC, field solving, simulation, TDR, or physical measurement.
