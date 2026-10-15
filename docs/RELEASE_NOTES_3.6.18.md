# WayriCAD 3.6.18

Trace Refiner is now an independently installable KiCad plugin, with its own
toolbar icon, native preview, illustrated guide and command-line interface.
It removes small track jogs within explicit displacement and shortening bounds.

- Scope the review to selected tracks, nets, native net classes or copper layers.
- Preview changes before running independent native connectivity and DRC checks.
- Apply approved changes with in-window Undo/Redo, or export a new project from the CLI.
- Keep endpoints, contacts, branches, widths, layers and protected routing intact.

Install `WayriCAD-trace-refiner-0.1.0-PCM.zip` with **Plugin and Content Manager →
Install from File**, or refresh the WayriCAD package repository. Restart PCB Editor.
See the [Trace Refiner guide](../trace_refiner_plugin/README.md) for the workflow,
CLI examples and limits. The package includes offline Help and its own icon.

The Python distribution advances to 3.6.18 and adds `wayricad-trace-refiner`.
Use KiCad 10's native Python for analysis; ordinary Python can display CLI help.
The other 20 PCM packages retain their published versions and download hashes.
Install only the tools you need; the full catalogue remains available in PCM.

Windows with KiCad 10.0.6 is the native validation target. Linux/macOS native GUI
and KiCad 11 remain unverified. Existing DRC errors on a proposed chain, new
findings, potentially capped baselines and custom length/skew/pair rules block
refinement. This is geometric cleanup, not automatic routing or timing tuning.
The public Marble board was used for preview scale checks; its existing DRC
baseline blocks applying changes. [Validation evidence](audits/TRACE_REFINER.md).
