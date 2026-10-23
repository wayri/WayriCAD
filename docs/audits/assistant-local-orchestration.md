# Local Assistant implementation and validation

WayriCAD Assistant is first distributed in release 3.6.28 as a testing package. The supported action catalogue and applicability limits below still apply.

## Implemented contract

The standard-library matcher compares normalized tokens and character trigrams with a fixed action catalogue. It fills typed slots from explicit text, saved-project context and visual selections. Ambiguous interpretations and missing numerical inputs require clarification. This is bounded intent matching, not a general language model or a downloaded neural model.

The catalogue contains 56 actions: a tool catalogue plus registered help and substantive CLI operations across the 23 existing plugins. It does not expose every operation of every plugin. Each adapter owns its argument construction, input schema, output paths and declared assumptions. Multiple tasks can be separated by “then”, “also” or a semicolon.

Guard-via requests have a separate preview action. Selected signal nets may fill the route scope, but the guard net must be supplied explicitly and must differ from those signals. For example, request guard vias along signal net CLK with guard net GND, spacing 2 mm and offset 1 mm. Review the resulting candidates in Via Stitching before applying them.

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

## Visual feedback follow-up

Native action icons are shared through the common form/workflow helpers. They retain text, tooltips, existing artwork and command handlers. The icon cache follows native DPI/system colours. Workflow headers show numbered stages and status; an error takes precedence over a completed stage.

Assistant adds task states, result counts, an activity indicator and an expandable board viewport. Exact selected nets accent pads, tracks, vias and zone borders while unrelated copper is muted. Focus selection and fit board are explicit camera actions. Shared snapshot selection does not replace proposed geometry, and hover/probe overlays retain cached pixels. Conservative arc envelopes and zone outlines remain approximate display context.

The native checks passed: 21 Assistant window tests, 5 highlight tests, 9 preview-cache tests, 8 layout/accessibility tests and 6 icon/workflow tests. The actual public Marble capture highlights 563 saved copper items on +3.3P without changing its source. Live editor handoff uses the existing verified selection/context helper, but the new button's IPC calls were tested with mocks, not a running PCB Editor. No claim of live-host validation is made.
