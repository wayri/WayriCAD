# WayriCAD Design Variant Workbench 3.0.0

A standalone Python/Tkinter application and KiCad 10 ActionPlugin for working with KiCad design variants safely. The menu action passes the active project to a detached Workbench process.

The original reason this tool exists is still a first-class feature: **choose a named variant and make it the new `<Default>` without silently changing the effective configuration of the other variants**. In 0.5.0 that operation has its own dedicated **Merge / Set Default** tab and is kept separate from ordinary variant editing.

The rest of the application has grown into a production-oriented Variant Workbench with a matrix editor, comparisons, validation, PCB synchronization auditing, controlled part substitution, manufacturing-release generation, and lifecycle operations.

> **Important:** the tool edits KiCad files directly for operations that KiCad 10 does not expose through the schematic IPC API. All writes use preview/review, exact input hashes, backups, S-expression validation, atomic replacement, and rollback attempts. Save and close the affected KiCad project before applying a write operation.

---

## Main tabs

### 1. Dashboard

Project-wide summary and navigation:

- named variants and differences from `<Default>`
- number of changed instances
- DNP and BOM-excluded counts
- Value / Footprint / custom-field changes
- variant health status
- quick links to Merge, Validate, PCB Sync, and Manufacturing Release

### 2. Merge / Set Default — the original core function

This remains its **own tab** and uses the original snapshot/rebase engine.

Supported modes:

- **Promote and remove source** — make the selected named variant `<Default>` and remove that now-redundant named variant.
- **Promote and keep source** — make it `<Default>` but retain the source as an equivalent named variant.
- **Swap with Default** — make the selected variant `<Default>` and preserve the previous Default under a new variant name.

The critical behavior is semantic rebasing. Example:

```text
Before

<Default>   R1 = 10k
Production  R1 = 22k
Legacy      R1 = 10k
Test        R1 = 47k
```

Promoting `Production` results in:

```text
After

<Default>   R1 = 22k
Legacy      R1 = 10k   # explicit override is created as needed
Test        R1 = 47k
```

The other variants retain the same **effective** values/flags they had before the Default changed.

The guided flow is:

```text
Step 1  Select named variant
   ↓
Step 2  Choose promote / keep / swap behavior
   ↓
Step 3  Preview semantic rebase
   ↓
Step 4  Review exact changes and apply with backup
```

### 3. Variant Matrix

A spreadsheet-style project view with components/sheet instances as rows and variants as columns.

Features:

- Default plus all named variants side by side
- filter/search references, files, values, and states
- visually highlight rows that differ from Default
- visually highlight staged edits
- edit a **named** variant without disturbing Default or other variants
- edit Value, Footprint, Manufacturer, MPN/custom fields, DNP, BOM/POS/board/simulation flags
- stage multiple changes before applying
- preview the complete semantic/file diff before write

Direct editing of `<Default>` is intentionally refused here. Default-changing operations belong in **Merge / Set Default**, where the other variants can be rebased safely.

### 4. Compare

Read-only two-variant comparison across the complete project.

Compares:

- Value
- Footprint
- arbitrary/custom fields
- DNP
- Exclude from BOM
- Exclude from position files
- Exclude from simulation
- Exclude from board

The comparison can be exported to CSV.

### 5. Validate

Variant-aware health/lint checks with severity-colored feedback.

Checks currently include:

- shared/multi-project schematic instance data that is unsafe to rewrite
- legacy variant `in_bom` serialization semantics
- redundant variant overrides
- empty Value on fitted symbols
- empty Footprint on on-board fitted symbols
- fitted-but-BOM-excluded states
- fitted-but-position-excluded states
- Footprint changes between variants
- named variants serialized in schematics but missing from project metadata
- metadata-only variants that currently inherit Default

The Manufacturing Release tab blocks on validation **errors**.

### 6. PCB Sync Audit

Read-only audit of the schematic's effective variant states against the `.kicad_pcb` variant state.

It checks, per reference/variant where representable on the PCB side:

- presence and uniqueness of references
- board-level variant metadata
- DNP
- Exclude from BOM
- Exclude from position files
- Value
- Footprint
- variant field values

It also explains properties that are schematic-only rather than pretending the board serialization supports them.

The tab provides:

- `<All variants>` or one-variant scope
- Error / Warning / Info coloring
- repair guidance
- CSV export

Typical repair loop:

```text
1. Save schematic changes
2. In KiCad: Update PCB from Schematic
3. Save PCB
4. Reload/refresh Workbench
5. Run PCB Sync Audit again
```

The audit is deliberately **read-only** in 0.4.0. It does not rewrite a PCB behind KiCad.

### 7. Part Substitution

A guided, safer variant-editing view for component substitutions.

It can stage changes to:

- Value
- Footprint
- Manufacturer
- MPN
- other fields
- DNP and assembly/exclusion flags

Before a substitution can be staged, the UI requires an explicit electrical/function compatibility confirmation. If the Footprint changes, it also requires explicit pad-map/mechanical compatibility confirmation.

#### Current KiCad 10 limitation

0.4.0 does **not** fabricate or write experimental/custom symbol pin-map overrides. The safe mode changes fields and assembly attributes only. True automatic library-symbol replacement + pin-map authoring is intentionally deferred until it can be represented and validated without guessing.

### 8. Manufacturing Release

Generates a selected variant's release package through `kicad-cli`.

Selectable outputs:

- ERC report
- variant BOM
- schematic PDF
- DRC + schematic parity report
- Gerbers
- drill files
- variant position CSV
- variant assembly/fabrication PDF
- variant STEP model
- SHA-256 manifest
- optional ZIP package

The release flow is guided:

```text
Step 1  Choose variant
Step 2  Choose outputs / kicad-cli / release folder
Step 3  Preview every CLI command
Step 4  Generate
```

Safety gates:

- variant lint errors block release
- PCB Sync errors block release by default when a PCB exists
- the sync gate can be explicitly disabled for an intentional exceptional workflow
- every project input is SHA-256 snapshotted at release preview
- if schematic/project/board files change after preview, generation is refused until previewed again

The generated `variant_manifest.json` records:

- Workbench version
- selected variant
- root schematic and PCB
- `kicad-cli` executable/version
- exact CLI commands
- SHA-256 hashes of release input design files
- SHA-256 hashes and sizes of generated output files

### 9. Manage

Lifecycle operations that do **not** change which configuration is Default:

- Rename variant
- Duplicate / create variant from a named variant or `<Default>`
- Delete variant
- Clean redundant overrides

Default-changing behavior stays in the dedicated **Merge / Set Default** tab.

---

## Write-safety model

For variant file-write operations the engine:

1. Parses KiCad S-expressions while retaining exact source spans.
2. Resolves effective state per hierarchical instance and per variant.
3. Builds a semantic plan before touching disk.
4. Regenerates only the required variant state.
5. Re-parses generated S-expressions before Apply.
6. Preserves Windows CRLF or LF line endings.
7. Re-checks exact raw-byte SHA-256 hashes immediately before Apply.
8. Creates timestamped backups of **every file before the first write**.
9. Writes by atomic replacement.
10. Attempts rollback from backups if a multi-file write fails.

It refuses unsupported/ambiguous structures rather than silently guessing. It also refuses every write when a KiCad `.lck`/`.lock` file exists beside any file in the plan, including unattended CLI writes.

Backups look like:

```text
project.kicad_sch.variant-manager.20260811-160000-123456.bak
project.kicad_pro.variant-manager.20260811-160000-123456.bak
```

Compatibility logic also retains support for the older pre-2026-03-06 variant `in_bom` serialization meaning and for KiCad 10 flat multi-top-level-sheet projects.

---

## Installation and standalone use

Install **WayriCAD Design Variant Workbench** from the WayriCAD repository in KiCad's Plugin and Content Manager. For a manual installation, extract the complete package into KiCad's ActionPlugin directory:

- Windows: `~/Documents/KiCad/10.0/3rdparty/plugins/wayricad_variant_workbench`
- macOS: `~/Documents/KiCad/10.0/3rdparty/plugins/wayricad_variant_workbench`
- Linux: `~/.local/share/KiCad/10.0/3rdparty/plugins/wayricad_variant_workbench`

Restart KiCad after installation. The PCB Editor ActionPlugin starts the independent Workbench with the active schematic when it can be resolved.

The same standard-library engine can be run outside KiCad from the installed/package directory:

```bash
python kicad_variant_manager.py
```

Pass a schematic path and CLI options for non-GUI automation as shown below.

### Why the plugin launches an independent Workbench process

KiCad 10 does not provide the live schematic editing surface needed for these operations. The ActionPlugin resolves the active project from the open PCB, then launches the Workbench as a **detached process**.

This is deliberate: the Workbench remains open while you save/close KiCad before applying a schematic/project-file transformation.

Plugin workflow:

```text
PCB Editor → Design Variant Workbench
                ↓
       active project detected from PCB path
                ↓
       independent Workbench window
                ↓
       inspect / compare / preview
                ↓
       save & close KiCad if a file write is required
                ↓
       Apply with backup
```

Manufacturing exports in KiCad 10 are generated through `kicad-cli`, which is the supported route used by the Workbench.

Optional standalone IPC dependency:

```text
kicad-python==0.7.1
```

The PCB Editor launcher itself does not depend on IPC readiness. Standalone IPC project detection remains available when `kicad-python` is installed.

---

## CLI

Read-only inspection:

```bash
python kicad_variant_manager.py project.kicad_sch --list
python kicad_variant_manager.py project.kicad_sch --lint
python kicad_variant_manager.py project.kicad_sch --pcb-sync
python kicad_variant_manager.py project.kicad_sch --pcb-sync Production
python kicad_variant_manager.py project.kicad_sch --compare "<Default>" Production --csv compare.csv
```

Variant transformations:

```bash
python kicad_variant_manager.py project.kicad_sch --promote Production --preview
python kicad_variant_manager.py project.kicad_sch --promote Production --keep-source --preview
python kicad_variant_manager.py project.kicad_sch --swap-default Production "Old Default" --preview
python kicad_variant_manager.py project.kicad_sch --rename Prototype EVT
python kicad_variant_manager.py project.kicad_sch --duplicate "<Default>" "New Variant"
python kicad_variant_manager.py project.kicad_sch --delete Obsolete
python kicad_variant_manager.py project.kicad_sch --clean --preview
```

For unattended CLI writes, add `--yes`. The same backup/hash/atomic-write safeguards remain active.

The Manufacturing Release workflow is currently exposed through the guided GUI, where the lint/sync gates and command preview are visible.

---

## Test coverage

Run the Workbench tests:

```bash
python -m unittest discover -s tests -v
```

Run compatibility/regression tests inherited from the original Variant → Default promoter:

```bash
python -m unittest discover -s compat_tests -v
```

The imported 0.4.0 test baseline contains **41 automated tests**. WayriCAD 3.0.0 adds integration tests for lock-file refusal, manifests, help, and icon assets.

- 27 Workbench/manager tests
- 14 compatibility/regression tests

Coverage includes:

- promote/rebase and keep-source behavior
- swap Default while preserving old Default
- rename / duplicate / delete / clean
- hierarchy conflict refusal
- metadata-only variants
- flat multi-root projects
- old `in_bom` semantics
- CRLF preservation
- stale-preview rejection
- backup behavior
- matrix state/patching
- linting
- PCB variant parsing/sync auditing
- missing/stale PCB variant detection
- variant-aware `kicad-cli` release command construction
- ensuring variant arguments are only used on CLI exports that support them
- release-preview design-file hash snapshots and stale-release rejection

The GUI was also smoke-launched under a virtual X display during packaging. This environment does not include a full KiCad 10 desktop installation, so the packaged plugin should still be trialed on a copied real project before being adopted into a production release flow.

---

## Current limitations

- KiCad 10 focused.
- PCB Sync Audit is read-only.
- True automatic symbol-library substitution / custom pin-map override authoring is not written in this version.
- Variant inheritance/dimensions/rule-engine features are not yet materialized; the file engine remains compatible with normal KiCad variants.
- A schematic carrying instance data for multiple projects is refused for unsafe write operations.
- If a variant introduces a field that cannot be safely synthesized with the required KiCad field geometry, the Workbench refuses rather than inventing geometry.
- Unknown/future variant S-expression tokens are refused until explicitly supported.
- For write operations, save and close the affected KiCad project before Apply.

---

## PCM package layout

The WayriCAD PCM archive contains only the runtime, documentation, manifests, and icons required by KiCad:

```text
variant_workbench_plugin/
|-- __init__.py
|-- legacy_action_plugin.py
|-- metadata.json
|-- requirements.txt
|-- variant_manager_plugin.py
|-- kicad_variant_manager.py
|-- help.html
|-- help-workflow.png
|-- icon.png
|-- icon-light-32.png / icon-light-64.png
`-- icon-dark-32.png / icon-dark-64.png
```

The original upstream 0.4.0 source archive also used the following development layout. Its installers, duplicate standalone runtime, and upstream test tree are intentionally not duplicated in the PCM payload:

```text
kicad_variant_workbench_v0.4.0/
├─ README.md
├─ CHANGELOG.md
├─ install_ipc_plugin.py
├─ install_ipc_plugin_windows.bat
├─ standalone/
│  ├─ kicad_variant_manager.py
│  ├─ KiCadVariantWorkbench.pyw
│  ├─ KiCadVariantManager.pyw        # compatibility alias
│  ├─ run_variant_workbench.bat/.sh
│  └─ run_variant_manager.bat/.sh    # compatibility aliases
├─ ipc_plugin/
│  └─ kicad_variant_manager/
│     ├─ plugin.json
│     ├─ requirements.txt
│     ├─ variant_manager_plugin.py
│     ├─ kicad_variant_manager.py
│     └─ light/dark toolbar icons
├─ tests/
│  ├─ test_variant_manager.py
│  └─ test_workbench_features.py
└─ compat_tests/
   ├─ test_variant_promoter.py
   ├─ test_edge_cases.py
   └─ test_more.py
```

---

## Relevant KiCad documentation

- KiCad 10 command-line interface: `https://docs.kicad.org/10.0/en/cli/cli.html`
- KiCad IPC API for add-on developers: `https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/`
- KiCad S-expression format: `https://dev-docs.kicad.org/en/file-formats/sexpr-intro/`
