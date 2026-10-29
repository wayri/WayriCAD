# Simulation setup and result files

`wayricad_runtime.project_results` stores complete PI, SI, thermal and Quick
EMerge beta result objects as integrity-checked JSON. The optional immutable
canonical library uses these project-local paths:

```text
.wayricad/results/quick-pi/<64-character-content-identity>.json
.wayricad/results/quick-si/<64-character-content-identity>.json
.wayricad/results/quick-therm/<64-character-content-identity>.json
.wayricad/results/quick-emerge/<64-character-content-identity>.json
```

There is no timestamp-based filename, mutable index, pickle, database, reference
download or hidden rich object state. A record retains its original root shape:
PI `mesh` and `result`, SI `path`/`eye`, thermal grids, active-cell coordinates,
layer-major frames, exact identifiers and hierarchical net names remain in their
existing locations. Unknown samples remain `null`; repeated time samples and
every saved array element are retained. The helper does not run a solver or
manufacture geometry, units or input fingerprints.

## Save and load in the plugins

1. Complete a simulation in Quick PI, Quick SI or QuickTherm, then choose
   **Save simulation…**. If several results are available, choose the completed
   study to retain. Existing HTML/PDF/report exports remain separate.
2. Choose the destination and filename in **Save complete simulation data**.
   The chooser starts in the saved PCB’s project folder, with a readable
   `<board>.<plugin>.results.json` name. An explicit overwrite prompt protects
   an existing chosen file. The content ID remains deterministic inside it.
3. Choose **Load simulation…** and select its JSON. Only that file is read;
   opening the library does not scan and parse every archived simulation.
4. The native **Saved simulation • read-only** window shows available saved
   fields, graphs, time steps and probes. **Advanced data** retains the complete
   numerical structure, with paged expansion for large arrays.

Loading does not run a solver, replace active setup controls, change sink
currents, select objects in the current editor or modify a board. The source
banner distinguishes matching, stale and unverified data. Historical data stays
available even when the current board has changed. Plot limits are visible;
the stored arrays are never shortened to fit a plot.

Keep these JSON files with the project when transferring it. Open the same
root-shaped records in Pocket KiView / the KiCad GitHub viewer alongside their
matching PCB. Copying only the JSON retains numerical results but does not
include the original board or external model files. Unsupported viewer plots
remain full numerical data rather than acquiring fabricated geometry.

## Saved-viewer examples

The three `help-saved-simulation.png` images in the Quick PI, Quick SI and
QuickTherm plugin folders are 1080 × 820 native wx client-area captures on
Windows with KiCad 10.0.6 / Python 3.11.5. They load the public
[`pocket-kivi` examples](examples/pocket-kivi/README.md), saved through this
library and reopened without solving. The plots show PI copper potential, SI
eye traces and the thermal transient's third stored frame at 1 s.
These are illustrative example inputs, not measured hardware results. No
private project names, machine paths or credentials are present; no redaction
was needed. Plots retain unknown values instead of substituting a temperature
or voltage. The complete arrays remain in each saved JSON.

## API and integration

```python
from wayricad_runtime.pocket_report import evidence_context
from wayricad_runtime.project_results import save_result, list_results, load_result

# completed_bundle retains the original solve-time saved PCB fingerprint.
evidence = evidence_context(
    completed_bundle, tool="Quick PI", package="quick_pi_plugin",
    board_path="C:/Projects/Example/board.kicad_pcb",
    units={"potential_V": "V", "cell_power_W": "W"},
    coordinate_frame="KiCad PCB XY in mm",
    z_basis="front-depth",  # Only if the producer actually declares this basis.
)
receipt = save_result(
    "C:/Projects/Example", "quick-pi", completed_bundle, pocket_kivi=evidence,
)
records = list_results("C:/Projects/Example", plugin="quick-pi")
loaded = load_result("C:/Projects/Example", receipt["relative_path"], plugin="quick-pi")
bundle, state = loaded["bundle"], loaded["receipt"]
```

## Editable setup files

**Save setup…** and **Load setup…** are separate from numerical results. Both
open a file chooser in the saved PCB’s project directory. A suggested name is
`<board>.<plugin>.setup.json`; choose another location or name if needed.

Setup files contain a versioned plugin identifier, the original saved PCB hash
and the editable inputs. Load validates the complete input before applying it,
clears old results and does not run a solver. A changed board requires explicit
review; missing nets/pads or incompatible models are reported rather than
silently dropped. Preserve referenced external IBIS files when moving an SI
setup; altered or missing model files cannot be substituted automatically.

Quick PI's main setup includes copper model/material/mesh controls, selected
net and exact source/sink pads, multipin choices, additional loads, package
contacts, series request and return-review settings. QuickTherm includes field
mappings, component scope/overrides/limits, heat paths and reviewed materials,
mounting contacts, imported current-board PI losses and transient settings.
Quick SI includes route/eye controls, return pins, study/crosstalk cases and
IBIS assignments. Quick PI’s AC, multi-rail/shared-return, electrothermal,
transient/shunt-capacitor and PDN-bank dialogs each provide their own mode-tagged
setup Save/Load pair. Their suggested names include the study type to keep
these files separate from the main copper setup. Draft controls, alternate
AC recipes, capacitor banks and reviewed material metadata are retained. Solver applicability and numeric input checks still apply
when running; loading a setup does not qualify its physical assumptions.

The canonical hidden `.wayricad/results/` API remains available for deterministic
CLI libraries. Native Save/Load accepts explicitly chosen names and paths;
report exports and setup files are separate formats, with actionable errors if
the wrong kind is selected.

Public signatures are:

```text
save_result(project_root, plugin, bundle, *, pocket_kivi=None, version=None, destination=None, protected_sources=())
load_result(project_root, path, *, plugin=None, chosen=False)
list_results(project_root, *, plugin=None)
```

Canonical plugin names are `quick-pi`, `quick-si`, `quick-therm` and `quick-emerge`. Short aliases
`pi`, `si`, `therm`/`thermal` and their existing source-package names are accepted
at the API boundary; stored names and directories always use the canonical form.
`list_results` checks records and returns receipts sorted by canonical plugin and
content identity, with a 1,000-record bound. This order expresses content, not
creation date. Invalid or corrupted records raise an error rather than silently
disappearing from the library.

The returned receipt includes absolute `path`, project-relative `relative_path`,
`identity`, `plugin`, actual `producer_version` (or explicit `None`), file `bytes`
and `sha256`, `source_state`, `source_issues`, `source_path`, `source_sha256` and
`can_restore`. Saving also returns `created`; for the canonical hidden library it is false
when exact identical bytes already exist. Named saves atomically replace only
the explicitly chosen output after the native overwrite confirmation. Loading returns the complete independent producer `bundle` with
only library metadata removed, alongside its receipt. Portable export metadata
and original producer fields remain available.

Source certification is explicit. Pass the existing portable-export evidence
dictionary for a saved-board result; it must carry the **original solve-time**
fingerprint. The library reuses the portable helper's source checks and path
relocation, with the project directory as `source_root`. The PCB must belong to
that project. Existing live/unsaved/snapshot evidence cannot be overridden by
supplying a current disk hash. A loaded portable payload may be saved again
with matching original evidence; conflicting portable metadata is rejected.

For circuit-only AC/transient models or historical data without original PCB
evidence, pass `pocket_kivi=None` and the actual producer `version` if known.
Their full JSON is preserved with an **unverified** source state. No PCB binding
is inferred from a study/model hash. Recognized filesystem metadata is relocated
to project-relative paths, even for unverified records; external references keep
their original fingerprint/absence under a stable `_external/...` alias. This is
lexical relocation only: it does not read those sources, compute a replacement
hash, add a PCB binding or change any simulation array, net name or object ID.
Do not catch a stale/conflicting saved-board
error and silently retry with no evidence: surface that error and retain the
result for explicit historical inspection instead.

## Current, stale and unverified

On every load/list, the library compares the original project-relative source
fingerprints with current bytes. Recorded absent files, such as custom rules,
must remain absent. Modified rules, missing boards, source links and changed
bytes produce **stale** state. Current source checks do not alter the record,
its original hash, its identity or its numerical arrays.

| Source state | Meaning | Native use |
| --- | --- | --- |
| `current` | Explicit saved-board evidence and all declared fingerprints match current project files. | Data restoration may be considered; `can_restore` is true. |
| `stale` | A verified historical result has unavailable or changed source evidence. | Inspect saved plots/data read-only; no rebinding, selection or rerun from this result. |
| `unverified` | No verified saved-board evidence was provided when saving. | Inspect read-only; `can_restore` is false even if a coincidental path/hash matches. |

`can_restore` is a necessary source-custody condition, **not permission to mutate
or cross-select a live editor**. The producer adapter must also verify the
originating editor's project/file and native UUID mapping, retain its source
guards and clear stale previews. A content hash establishes integrity, not
producer authenticity, model applicability, mesh convergence or solver accuracy.

The shared portable path helper relocates external input paths to `_external/...`
aliases but does not copy files. If such a declared input is absent in the
project, the loaded result is stale/read-only; the library never follows a
reference outside the project or fetches it. For unverified data, numerical
fields and existing hash values are retained while recognized path fields are
relocated, without being presented as a saved-board certificate. Hierarchical
names such as `/Front outputs/SLOT1` remain exact. Review free-form text/private
metadata before sharing; this is not a general redactor.

## Common CLI

The common CLI performs data operations only: it never runs a solver, launches
an editor, signs in, fetches references or computes a new PCB binding. Use the
module from a source installation:

```text
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example list
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example list --plugin quick-pi
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example save result.json --plugin quick-pi --version ACTUAL_PRODUCER_VERSION
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example show .wayricad/results/quick-pi/IDENTITY.json
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example show .wayricad/results/quick-pi/IDENTITY.json --full
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example save result.json --plugin quick-pi --output board.quick-pi.results.json
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example show board.quick-pi.results.json --plugin quick-pi
```

Replace `IDENTITY` with the receipt's full 64-character identity. CLI plugin
choices include all four canonical names, including `quick-emerge`. Input
JSON/evidence filenames are relative to the process working directory; chosen
record paths, `--output` paths and relative evidence `board_path` values are
relative to `--project`. `show` accepts a readable named JSON within the project
or an absolute JSON filename elsewhere; it validates the embedded plugin, schema
and content identity rather than requiring a hash-shaped filename.

`save` defaults explicitly to **unverified/read-only**, including when an input
contains hash-shaped metadata. Its JSON receipt makes that state visible. Actual
producer `--version` is optional and remains unknown when omitted. Strict input
uses the same 64 MiB/depth/duplicate-key/nonfinite rejection as library loads.
Named `save --output` appends `.json` when no extension is supplied. Existing
named outputs require explicit `--overwrite`; the default remains the immutable
hidden library when `--output` is omitted. Input, evidence and declared source
files are protected even with `--overwrite`. No data arrays are truncated to
fit the 64 MiB record limit; oversized records fail with an actionable error.
Input and evidence files are never changed. Errors return exit status 2 with a
JSON diagnostic on stderr; successful operations return status 0 and JSON on
stdout. `list` emits receipts, and default `show` emits a single receipt without
printing the simulation arrays. Explicit `show --full` emits both `bundle` and
`receipt`, retaining every array element and the current/stale/unverified state.
This diagnostic envelope does not replace the root-shaped library file; open
the receipt's `.json` file directly in a saved-result viewer.

For a verified saved-board result, pass an explicit evidence JSON:

```text
python -m wayricad_runtime.project_results_cli --project C:/Projects/Example save result.json --plugin quick-pi --evidence original-evidence.json
```

The evidence object contains the existing portable-export keyword arguments:
required `board_path`, **original solve-time** `source_sha256`, `tool`, actual
`version` and `source_state: "saved"`; optional `units`, `coordinate_frame` and
`z_basis` must come from actual producer conventions. Unknown keys are rejected.
The board and fingerprints are fully checked by the existing saved-source
contract. An error never triggers a retry as unverified. Export this evidence
from the original completed result/workflow; calculating today's disk hash is
not a way to certify an older simulation. Supplied evidence is never inferred
from a study/model hash or from current files.

## Determinism, atomicity and bounds

The root `wayricad_saved_result` object adds schema
`wayricad.project-result/v1`, library `version: 1`, canonical plugin, actual
producer version, source-binding mode, declared fingerprints and full identity.
The identity is SHA-256 of canonical UTF-8 JSON with just the metadata's
`identity` field omitted. Canonical JSON sorts object keys, uses compact
separators and includes one final newline. Array order is untouched. A receipt
also reports the full file-byte hash, which differs from this self-reference-free
content identity.

Identical inputs produce identical bytes and paths. Existing records are never
replaced, including records whose contents were mutated under an old identity.
A collision or corrupted existing file is an error. New content is staged and
flushed in the target directory, then published exclusively: Windows uses a
non-replacing atomic rename; POSIX uses an exclusive hardlink followed by staging
cleanup. A source change during publication removes only that call's newly
created record. This is process-level publication, not a multi-file/power-loss
transaction.

Library and record paths must remain inside the existing project directory.
Symbolic links and Windows reparse/junction paths are rejected for record access;
all declared source verification stays within the project. Final record paths
cannot alias a protected original source or settings file. As with other local
filesystem operations, a hostile process concurrently replacing directory paths
requires operating-system isolation beyond this portable helper.

Saving and loading enforce strict JSON, at most 64 MiB including metadata and
64 nesting levels. Duplicate keys, NaN/infinity, circular data, invalid UTF-8,
non-string keys and incompatible metadata are rejected. Load also verifies the
plugin, canonical filename, exact content identity, canonical file bytes and
agreement between source metadata and payload fingerprints. There are no
automatic format migrations or fallback defaults.

## Producer restoration hooks

Producer UIs retain responsibility for controls, supported result modes and
plot/probe bindings. Useful existing boundaries are:

- Quick PI: full `geometry`/`mesh`/`result` objects, request/terminal IDs and
  existing report/draw functions. Keep batch child descriptors distinct from
  full case results; restore actual case bundles, not descriptor summaries.
- Quick SI: saved reports contain path/eye data and endpoint/board UUID evidence.
  Native route reconstruction also needs the worker's complete `path_data` and
  `board_item_ids`; preserve those in the saved payload if native route restore
  is offered. Use the existing `restore_path` UUID/source checks. A saved report
  alone supports plots without inventing missing native path objects.
- QuickTherm: full `quick_therm`, `board_thermal_view`, `thermal_network`, request,
  probes and transient `spatial_index`/frames. Use existing frame/probe helpers;
  do not flatten layer-major arrays or turn absent spatial cells into values.

The pure persistence module does not own widgets; `project_results_ui.py` wires
the Save/Load actions and the separate read-only viewer described above. Its JSON
can also be opened by saved-result viewers, including Pocket KiView, without
executing scripts. Root PI and existing SI/thermal shapes remain compatible;
shared metadata does not make unsupported geometry into a supported plot.

## Focused checks

```text
python -m pytest tests/test_project_results.py tests/test_project_results_cli.py --basetemp .validation/project-results-tests -q
python tools/validate_docs.py --source-only
```

Tests cover canonical idempotence, complete PI/SI/thermal arrays and nulls, source
changes and recorded absence, corruption, plugin mismatch, size/depth/strict JSON,
path traversal/link rejection and failed-publication cleanup. Native editor and
live provider workflows are separate integration checks.
