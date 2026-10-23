# Local Assistant implementation and validation

WayriCAD Assistant 0.1.0 is a development addition after the published 3.6.27 release. The existing public package feed is unchanged.

## Implemented contract

The standard-library matcher compares normalized tokens and character trigrams with a fixed action catalogue. It fills typed slots from explicit text, saved-project context and visual selections. Ambiguous interpretations and missing numerical inputs require clarification. This is bounded intent matching, not a general language model or a downloaded neural model.

The catalogue contains 55 actions: a tool catalogue plus registered help and substantive CLI operations across the 23 existing plugins. It does not expose every operation of every plugin. Each adapter owns its argument construction, input schema, output paths and declared assumptions. Multiple tasks can be separated by “then”, “also” or a semicolon.

Execution uses argument arrays and an isolated Python worker. It does not evaluate generated Python or shell commands. Placement and routing actions produce previews; applying changes remains in their originating tools. Existing solver applicability, estimates, unknowns and failure statuses remain visible.

Plans bind the saved board, project/rule companions and recursive schematic inputs to hashes. Inputs are checked before and after each step. Source discovery follows declared child and flat top-level sheets, rejects unresolved variables and bounds discovery to 300 files and 512 MiB. These checks detect saved-file changes; they are not a cryptographic authorization signature or protection against another process racing a file read. Save editor changes before planning.

Each run owns a new output directory, bounded logs, a combined HTML report and JSON records. Generated settings are recompiled and checked by the worker. Cancellation and timeouts terminate the owned process tree. Unexpected monitoring failures also reap the worker. Results retain tool reports and source provenance.

## Evidence

Validation was performed on Windows with Python 3.14 for portable tests and KiCad 10.0.6 / Python 3.11.5 / wxPython 4.2.2 for native window tests.

- Actual GUI → planner → existing RLC CLI execution returned **49.928090751 Ω** for a microstrip with width 0.2 mm, reference height 0.1 mm and relative permittivity 4.2. The zero-thickness assumption and ESTIMATE limitations remain in the report.
- The independent PCM ZIP bundles private backend packages. An installed-only isolated worker completed a two-task microstrip calculation and catalogue request without importing the source checkout. A separate geometry, width 0.2 mm / height 0.18 mm / relative permittivity 4.3, returned **68.079493519 Ω** and effective permittivity **3.130333571**.
- Artifact hashes, saved run records, unchanged public-board inputs and stale child-schematic rejection were checked.
- Focused engine tests exercise actual workers, missing inputs, unit conversion, ambiguity, plan tampering, generated-settings tampering, timeout, cancellation, unexpected monitoring failure and log limits. Separate adapter/source tests exercise typed inputs, command construction and schematic discovery.
- Native window tests cover clarification, automatic execution, results, selection highlights, stale callbacks, resize behavior, persistent output folders and report confinement. Screenshots in the plugin README show actual native windows and actual calculations.

The native window was tested standalone. These checks do not establish a running-editor IPC toolbar workflow on all operating systems. Scientific/native dependencies of the executed tools are still required; the coordinator does not replace those runtimes or validate a complete engineering study merely by launching it.
