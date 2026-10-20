# WayriCAD 3.6.21

Multi-net PI/SI studies, explicit return copper, optional PI temperature feedback, clearer offline reports and a unified CLI catalogue across all 23 tools. Includes the improved Mechanical Check review workspace.

## Quick PI

- Configure independent rail cases with explicit sources and loads. Review errors per case rather than losing the whole study.
- Optionally solve a single-load DC supply/return loop using explicit load-ground and source-ground pads. Reports include return resistance, ground rise, combined voltage drop, delivered load voltage and total I²R loss.
- Check **Include Joule heating / temperature feedback** to configure a steady coupled study. Plain DC already calculates copper loss; temperature feedback requires explicit conductivity, temperature coefficient, material validity range and cooling boundaries.
- Physical feasibility uses the final loop or coupled operating point, not an obsolete supply-only or cold-baseline check. Source-current limits remain enforced.

## Quick SI

Select multiple nets, edit each route's source/receiver and driver/reference assumptions, and review the results case by case. Explicit return nets and return terminals are included in the geometric audit and reports. CLI adds `study` plus single-route return-net/source/load flags. Ambiguous or missing terminals remain errors, and changed PCB/project/rule files invalidate the study.

## Reports and automation

PI, SI and QuickTherm HTML reports have status/coverage summaries, provenance, section navigation, searchable/sortable tables and print controls. Existing interactive plots and probes remain available. Paired PI/Therm HTML/JSON publication supports recovery on write failure and rejects source aliases. PI batch reports link individual case evidence; SI studies compare route results.

Use `wayricad tools list`, `show`, `doctor` and `run TOOL -- --help` to find the supported CLI interface of all 23 plugins. This is broader headless access, not automatic parity with every GUI action. A new read-only Silkscreen CLI previews positions, sizing and guides; applying remains in PCB Editor. The `analysis-studies` job preset runs reviewed PI/SI models and a thermal configuration.

## Mechanical Check

The larger review viewport has a hideable/resizable findings sidebar, separate Findings/Measure/Display tabs, direct focus/isolation controls, improved filters and threshold details, and camera-preserving navigation. Empty filters, deselection and board changes clear stale findings. Updated native screenshots and offline help are included.

## Models and limits

Multi-net cases run independently: no shared-return interaction, inter-net fields, crosstalk or whole-bus qualification is inferred. Explicit PI return conduction currently supports one prescribed-current load and fixed-temperature 2.5D linear copper; temperature feedback and return-conduction cases are separate supported modes. Thermal feedback needs reviewed boundary/material inputs and convergence/validity checks. A completed calculation is not physical sign-off.

Native Windows checks use KiCad 10.0.6 and FreeCAD 1.1 where applicable. Linux/macOS native GUI, every display scale and every live-editor workflow remain unverified. See the [validation record](audits/RELEASE_3.6.21.md).

## Install

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, install updates and restart PCB Editor. Alternatively choose **Install from File** with a PCM ZIP from this release, without unpacking it.

The 17 IPC packages advance to 3.6.21. Native packages carrying the updated shared runtime are Fusion 0.9.10, Variant Manager 0.6.3, Silkscreen Labels 0.3.0, Trace Refiner 0.2.2, Component Arranger 0.1.2 and Layer Counter 0.1.2. Existing published binaries are not replaced.

[PI guide](../quick_pi_plugin/README.md) · [SI guide](../signal_integrity_advisor_plugin/ReadMe.md) · [Thermal guide](../quick_therm_plugin/README.md) · [All-tools CLI](TOOL_CLI_CATALOGUE.md)
