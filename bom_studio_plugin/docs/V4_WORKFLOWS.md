# WayriCAD BOM Studio 0.4 — Search, bulk actions, automation and live selection

Developer preview · 9 September 2026. This is an implemented update; native KiCad launch, native job-set execution, viewport behavior and the schematic relay have **not** been exercised in a KiCad host. Read `TEST_REPORT.md` before production use.

## 1. Advanced search and reusable filters

In **BOM workspace**, choose **Advanced search & saved filters**. Enter a query or add clauses with the field/operator/value builder. **Test count & facets** evaluates the actual shared Python query engine without changing the grid. Click a facet value to append a narrowing condition, then test or apply. Field names are case-sensitive; values are case-insensitive unless selected otherwise. Quote field names or values containing spaces.

```text
Reference~"R*" AND Value=10k
is:fit AND (missing:MPN OR missing:Manufacturer)
Footprint:"0603" AND NOT is:dnp
UnitPrice>0.10 AND UnitPrice<=2
raw.Value:"${" OR is:overridden
```

Supported operators are `:` (substring), `=` (exact), `!=`, `~` (wildcards `*` and `?`), and decimal `<`, `<=`, `>`, `>=`. `NOT`, `AND`, `OR`, parentheses, and implicit AND are supported; precedence is NOT, AND, OR. Plain words search row fields. Backslash escapes a matching quote or another backslash inside quoted text. There is no executable expression, regular-expression, SQL or JavaScript search mode.

`has:FIELD` / `missing:FIELD` inspect nonblank/blank values. Prefix a field with `raw.` or `resolved.` to choose its representation. `is:` supports `fit`, `fitted`, `dnp`, `dni`, `not_fitted`, `excluded`, `on_board`, `variable`, `overridden`, `error`, and `warning`. Error/warning predicates use component-specific existing BOM-data checks, **not** the separate health report or unassigned project-global issues. Numeric comparisons accept finite decimal data, not engineering units or currency conversion; `Value>4k7` is rejected rather than interpreted as 4700.

Unknown fields and malformed predicates fail closed. A stale or invalid compiled filter is not silently replaced with all parts. Search works on the committed workspace in the active variant, not unreviewed grid drafts. Quick search, population filter and advanced search run before grouping. Query results include count, references, IDs and four facets (Assembly, Manufacturer, Footprint, Sheet); each facet displays up to 100 distinct values.

**Save query as filter** stores name, description, query and case setting in the project sidecar. Save workspace to retain it across sessions. Load, delete, share and import controls are provided. A `wayricad-filters-1` JSON bundle contains filter definitions, not component rows, variables or library content. Literal search terms can still expose private information. Import conflicts require explicit Replace or renamed definitions. Saved filters do not silently change the active variant or assembly state. Limits: 100 saved filters, 4096 query characters, 256 tokens and 24 nesting levels.

## 2. Selection and bulk actions

Checkboxes select **edit targets**. They work on individual rows, complete displayed groups and expanded group members. **Select all N results** selects the full filtered result set, across pages. **Invert results** affects matching rows; **Clear selection** clears edit selection. The interface reports how many checked components are hidden by current filters.

**Bulk actions…** requires an explicit scope: selected parts (including selected parts now hidden), or every current filtered result. A recipe can have 1–30 ordered operations: Set, Fill empty, Clear value, Trim, Uppercase, Lowercase, Prefix, Suffix, Literal replace, Copy raw field, and Reset override to inherited/base behavior. Clear makes a field blank; it does not delete a symbol property. Boolean inclusion flags accept explicit boolean values, not string transformations. FIT/DNP/DNI shortcuts now open the same reviewed bulk transaction.

Add steps, choose fields and values, and select **Preview complete changes**. The preview exposes effective before/after changes, shared child-sheet occurrences and inheriting variants. Up to 500 changes are shown on screen; the full JSON review is downloadable. Nothing is applied at preview time. Type **EDIT**, acknowledge variable-expression loss when reported, then stage one undoable workspace transaction. Save workspace persists it. Native files remain unchanged until the separate **Review & native sync → APPLY** operation.

Recipes are data-only and shareable. Loading a recipe into the GUI loads operations; deliberately choose the current scope rather than silently importing another project's target UUIDs. CLI recipes may contain exact IDs or an explicit query, never both. An empty all-parts query needs `allow_all:true`. A stale plan or source-file change requires a fresh preview. Pending in-grid drafts must be staged/discarded before using these bulk actions. Conflicting edits to a shared base symbol are rejected, not resolved by row order.

Changing Value or MPN is not library-symbol replacement or qualification. Reference annotation, symbol placement/deletion, connectivity and footprint geometry remain KiCad responsibilities. Raw variable expressions are kept unless deliberately replaced. An exact generated-variable field still follows KiCad's protected generated-value rule.

## 3. CLI, repeatable pipelines and policy gates

**Automation & live link** contains a pipeline editor and job-set bundle generator. The complete command surface is documented in `CLI_REFERENCE.md`; ready-to-edit inputs are in `examples/automation/`. GUI and CLI share query, edit, check, health and export engines. CLI reads the saved native project plus the saved sidecar by default—not pending browser state or unsaved KiCad editor memory.

The `run` command is read-only for the project. It publishes a new directory containing a workspace snapshot, per-variant checks and selected health/analysis reports, selected BOM formats, and a SHA-256 manifest. All paths must be new; pre-existing output files are not overwritten. Checks always run. Health warnings/unknowns and eligible stock observations can be made release gates. If a chosen gate fails, the CLI exits 3 and publishes diagnostic reports plus a **FAILED** manifest, with **no BOM exports**.

The default health threshold is **none** and `require_stock` is false: existing advisory health does not unexpectedly block every project. Choose a stricter policy intentionally. Unknown evidence is not a passing qualification; a strict policy can require its resolution. Requiring observed stock still does not reserve inventory, certify a source or authorize purchasing. A strict example is expected to fail on the synthetic demo's incomplete evidence.

`verify` checks archive-directory contents against recorded file hashes, sizes and allowed paths. It is an integrity check, not approval: a FAILED report set can correctly verify as intact. Always inspect `release_status` or the original run status and exit code. SHA-256 manifests are not signatures. Runs contain absolute source paths, template defaults, variants and potentially proprietary evidence in `workspace_snapshot.json`; review before sharing. Published runs are inspectable snapshots, not a complete archived copy of all referenced external libraries or source files.

## 4. Run from KiCad job sets

Generate a bundle in the GUI using an **absolute intended extraction directory**, or use the `jobset` CLI command. It contains five files: `WayriCAD_BOM.kicad_jobset`, `run_wayricad_job.py`, `pipeline.json`, `job-bootstrap.json`, and `README_JOBSET.txt`. Extract all files into exactly the directory specified at generation. Review the interpreter, plugin and project paths, policy and output destination.

Open the generated `.kicad_jobset` in this project's KiCad Job Sets tab. It uses **Special: Execute Command**, keeps Ignore exit code disabled, and records the headless command result. Alternatively add its generated command to an existing job set; do not replace other manufacturing jobs. The runner puts outputs under KiCad's `JOBSET_OUTPUT_WORK_PATH/<pipeline name>` temporary location, allowing native output destinations to collect them. KiCad may not copy failed-job output to the final destination: inspect the job log or reproduce the failed pipeline directly with CLI for persistent diagnostics.

```sh
kicad-cli jobset run --file /path/jobs/WayriCAD_BOM.kicad_jobset --stop-on-error /path/Board.kicad_pro
```

KiCad's own `--output` argument chooses a destination by name/ID; it is not an arbitrary directory argument. The generated bundle has machine-specific paths. Regenerate after moving it, changing the interpreter or relocating the plugin/project. The Windows generator rejects `%`, `!` and double quotes in paths instead of guessing `cmd.exe` escaping. Native KiCad job-set and Windows shell execution still require host validation; the runner was tested with a simulated native output environment.

### Launch an interactive GUI from a job set

Use a separate user-initiated Execute Command job with an explicit GUI command:

```text
"C:\Path\Python\python.exe" "C:\Path\wayricad_bom_studio\cli.py" gui "C:\Projects\Board.kicad_pro" --detach
```

`--detach` starts a separate GUI process and returns only after it publishes a ready session. The ordinary `gui` command remains foreground and would keep the job waiting until Quit. Do not use a detached GUI as a manufacturing gate or in unattended CI. Disable **Record output** for this interactive job: its receipt includes a private session URL. Use **Quit** to stop the GUI; closing the tab alone is insufficient. The generated pipeline bundle is headless; it does not launch a GUI by itself. Detached launch was tested on Linux, not Windows/macOS or the native job-set host.

## 5. Optional bidirectional live selection

The implementation deliberately separates live **selection** from BOM data and native design edits. The optional adapter uses the official `kicad-python==0.8.0` package. The core GUI, CLI and exports need no third-party Python package; only live linking does. KiCad-managed plugin environments can install the supplied `requirements.txt`; standalone use needs the package in the same interpreter running WayriCAD:

```sh
python -m pip install -r /path/wayricad_bom_studio/requirements.txt
```

Dependency download requires connectivity once; no paid account, API key or supplier connection is involved. Offline environments can provision the package and its dependencies separately. This release does not bundle or test that official runtime against a real KiCad host.

Open the **saved project** in KiCad Manager, then open its PCB and schematic. Enable IPC in KiCad and configure the plugin interpreter. Enable native cross-selection and relevant centering/zoom preferences in both editors. Launch WayriCAD from its PCB Editor action. With inherited IPC context and the optional client available, WayriCAD attempts to discover the saved board's project and connect; otherwise Open project and Live link provide the manual route. An explicitly different project is never silently switched to the connected board.

**Live link…** shows mapping coverage, connection status and separate send/follow controls. Click any ordinary cell in an individual BOM row to select its mapped footprint. Click a grouped row to target the group's current members. Editing controls, checkboxes and double-click-to-edit are kept separate. PCB selection is polled approximately once per second; selecting a mapped footprint or one of its indexed pads/fields highlights the matching BOM component. The view can expand a group, go to its page and scroll to the item. It does not force OS window foreground or disturb an active input/dialog or unreviewed grid edits; deferred reveal is offered instead.

Selection from an editor does **not** become a bulk-edit selection. Use **Use linked parts as edit selection** deliberately. If a linked part is hidden by search, use **Reveal** to temporarily show linked parts, then **Restore filters**. A live selection never rewrites a saved filter. Echo suppression prevents a received selection from being immediately sent back.

Identity uses the full schematic instance UUID path plus symbol UUID, not reference text alone. Repeated sheets and multi-unit members are accounted for. Reference fallback is off by default and only permitted where UUID linkage is absent, never where a stored UUID disagrees. Ambiguous/unmapped targets block the outgoing operation rather than clearing selection and choosing something plausible. A project/board change, stale source file or connection failure disconnects the link. The adapter may change editor selection; it does not create/update/delete/save board objects. It does not synchronize active variants or BOM field edits into unsaved editor memory.

### What is and is not implemented for schematic focus

The KiCad 10 path is **BOM ↔ PCB IPC ↔ KiCad native schematic cross-selection**. Direct schematic IPC is not implemented here; current API documentation marks schematic access as a KiCad 11 addition. Consequently schematic-only components without a mapped footprint, editor launches outside a shared managed project, disabled cross-selection, or unmapped references cannot be guaranteed to relay. This is not a standalone schematic plugin action.

PCB zoom-to-selection is an **opt-in experimental** call to a single allowlisted tool action. KiCad documents `run_action` as unstable. A successful submission is reported as `submitted_unverified`, never proof the viewport moved. The relay cannot acknowledge schematic selection/focus independently. Neither relay nor actual viewport behavior has been tested in a KiCad host. The shipped bridge is an implementation to validate, not a claim of completed three-way host certification.

## 6. Host acceptance checklist

Use a disposable project copy. Verify one component and a group BOM→PCB, then footprint, pad and field PCB→BOM; verify schematic→PCB→BOM and BOM→PCB→schematic with native cross-selection enabled. Include repeated child sheets, multiple units, excluded/DNP parts and a schematic-only component. Confirm no wrong reference fallback, infinite echo or surprise bulk target change. Check zoom separately and leave it disabled when uncertain. Change projects, disconnect/reconnect, change selection during an active text edit and test hidden-row reveal/restore.

Compare CLI and GUI exports from the same saved workspace. Run both passing and intentionally failing native job sets and inspect output collection. Save external edits and explicitly reload; live selection is not live field synchronization. Do not perform native APPLY with KiCad editors open. Windows/macOS installation, SDK transport, native selection relay, job-set host behavior and KiCad 11 remain unexecuted acceptance tasks.
