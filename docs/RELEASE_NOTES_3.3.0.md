# WayriCAD 3.3.0: KiCad jobsets and automatic reports

Run saved-project report sequences from KiCad 10 Job Sets, a terminal or CI using
`wayricad jobs` or `wayricad-jobs`. See the [setup and workflow guide](../wayricad_runtime/JOBSETS.md).

- Create or merge a native jobset while preserving existing jobs and destinations.
- Start with fabrication, electrical inventory, selected-path PI/SI/RLC, or BOM Studio presets.
- Generate a linked local HTML index, JSON summary, logs and SHA-256 artifact manifests.
- Keep every run in a separate project report folder and collect it into the native jobset destination.
- Retain diagnostics on failure, enforce step dependencies, reject missing outputs,
  detect changed design inputs, and support timeouts and cancellation.
- Customize argument-array commands and variables without a shell between report steps.

Install the CLI wheel for automation; installing a PCM GUI plugin alone does not
provide the suite's terminal commands. Electrical workflows also require their
documented native/scientific runtimes. Existing GUI tools remain independently
installable. Help and README files now explain the report workflow.

## Validation and limits

Native KiCad 10 on Windows executed a three-job sequence with before/after checks,
paths containing spaces and report collection. A failing sequence propagated a
nonzero native jobset exit and retained its project-local diagnostics. PI, SI and
RLC inventory presets passed. The fabrication fixture produced an ERC violation;
its dependent BOM was correctly skipped while independent PCB checks completed.

Automated regressions cover unique runs, literal arguments, required outputs,
dependency failures, timeouts, cancellation, changed inputs, artifact hashes,
native jobset merging and invalid configurations. These checks do not establish
native GUI operation on other operating systems or KiCad 11.

Reports preserve each analyzer's existing numerical assumptions and limitations.
Successful command execution is not engineering approval. GUI-only tools do not
gain headless analysis automatically. Generated native jobsets contain local
project/interpreter paths and must be regenerated after relocation.
