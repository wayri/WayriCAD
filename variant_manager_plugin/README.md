# <img src="icon.png" width="48" height="48" alt="Variant Manager icon"> WayriCAD Variant Manager

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#compare-and-preview) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run variant-manager -- --help` |

CLI scope: Variant inventory, comparison and reviewed batch changes. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

Variant Manager is an independently installable KiCad 10 plugin for native assembly variants. It has its own icon, PCB Editor action, native desktop window and CLI. Fusion imports designs; Variant Manager manages their assembly configurations.

![Native Variant Manager comparing Default and Production](help-workspace.png)

This native Windows/KiCad 10.0.6 capture uses a generated one-resistor hierarchy. Production changes R1 from 10k to 22k and marks it DNP. The displayed path is a generic example. The rectangles are saved footprint envelopes, not a newly generated layout or a 3D rendering.

## Compare and preview

1. Open a saved project from **Tools → External Plugins → WayriCAD Variant Manager**, or run `wayricad-variants gui --project C:/Projects/Example/board.kicad_pro`. The plugin opens independently so you can close KiCad before applying changes.
2. Choose **Before** and **After** variants. The component table shows values, footprint assignments and local assembly flags. Sheet instances appear separately; parent-sheet flags are explicitly reported rather than silently counted as local symbol flags.
3. Choose **Top**, **Bottom** or **Both** to filter the saved board preview. Click a footprint or select table rows to highlight matching instances. Missing or ambiguous reference matches and parent-sheet exclusions are grey, not assumed included. The preview does not replace footprint geometry when a variant changes its footprint field.
4. Filter references, for example `J*`, and use **Select visible** for bulk operations. Select several named variants in the left list with Ctrl/Shift.

## Stage changes

| Action | Result |
|---|---|
| Create / Duplicate | Copy Default or a named variant under a new name. |
| Rename | Rename a definition and its instance overrides. |
| Delete | Remove all selected named definitions and overrides together; Default cannot be deleted. |
| Bulk edit | Set an existing property or assembly flag on selected exact hierarchy instances in selected named variants. |
| Merge | Combine source overrides into a target relative to Default. Conflicts stop the preview unless you explicitly choose source or target precedence. |
| Swap | Exchange two named configurations while retaining their names. |
| Promote | Make a named variant Default, preserving other variants' effective local states; optionally keep old Default under a new name. |
| Restore | Restore selected definitions from a verified backup while retaining current drawing geometry and Default. Replacing existing definitions requires explicit acceptance. |

Operations accumulate into one reviewed transaction. **All staged changes** lists added, deleted and changed states across the whole batch; **Compare selected variants** compares saved Before with staged After. The lower panel shows exact file differences. **Clear staged** discards the candidate, not source files. Export HTML, JSON or CSV review evidence before applying.

## Apply and recover

Save and close the project's schematic editor, PCB Editor and project manager. Keep Variant Manager open, tick the closed-project acknowledgement, and click **Apply reviewed changes**. It checks source hashes and locks, validates the candidate and creates a verified ZIP in `.wayri-variant-backups` before writing. Source changes or unsupported override tokens stop the transaction. Per-file write failures trigger rollback; the multi-file operation is not power-failure atomic.

Reopen KiCad afterward. Named variant edits affect native variant-aware outputs. If you promote a variant with changed footprint or placement flags, use **Update PCB from Schematic** and review the resulting PCB changes. Variant Manager does not move components or modify routing. A full source restore is available in the CLI and rewinds later design edits; use it only after reviewing its diff.

Failed staging retains the previous reviewed candidate and its operations, so you can correct the input and retry. Failed Apply retains the review for inspection but disables Apply; reload the saved project and build a new candidate before writing again. Reload discards staged work and clears the old inventory even if loading fails. Apply or clear a staged restore before adding other operations, and apply or clear an existing candidate before staging a restore. A source change since loading disables Apply and clears the closed-project acknowledgement; the review remains available for export, and reload is required before adding operations or restoring definitions. Failed exports retain the staged review and report how to retry with a writable output.

## CLI and batch jobs

```text
wayricad-variants list C:/Projects/Example/board.kicad_pro
wayricad-variants job C:/Projects/Example/board.kicad_pro operations.json
wayricad-variants job C:/Projects/Example/board.kicad_pro operations.json --apply --editors-closed --yes
wayricad-variants backups C:/Projects/Example/board.kicad_pro
wayricad-variants restore-variants C:/Projects/Example/board.kicad_pro backup.zip Production
```

The `job` command accepts a JSON array and previews by default:

```json
[
  {"op": "duplicate", "source": "Production", "name": "Prototype"},
  {"op": "merge", "source": "Prototype", "target": "Production", "policy": "error"},
  {"op": "swap", "left": "Production", "right": "Prototype"}
]
```

Bulk-edit operations use exact `key` identities from `list` output: `{"op":"edit","variant":"Prototype","keys":["<exact instance key>"],"fields":{"Value":"22k"},"flags":{"dnp":true}}`. A null field value restores the Default field value. Identity, hierarchy and absent properties cannot be edited. Use `--help` for backup verification, Default promotion and source restoration.

## Requirements and limits

KiCad 10 native schematic variants are required. PCM uses the native action-plugin interface and KiCad's bundled Python/wxPython; it does not create a separate pip environment. CLI comparison and batch operations need Python 3.10+, while the native window needs wxPython and its saved-board overlay needs `pcbnew`.

Reused sheet occurrences retain distinct variant overrides by UUID and instance path. Promoting conflicting states of the same reused symbol is refused because its serialized Default is shared. External/symlink hierarchies, unknown variant tokens, changed field schemas during restore and ambiguous identities are refused for writes. Existing unrelated unknown tokens are preserved. This tool manages variant definitions; it does not merge circuits or keep independent routing layouts per variant.

See [offline help](help.html) and [validation evidence](VALIDATION.md). The parser and backup service retain the standalone Variant Manager's MIT license and are packaged independently of Fusion.


## Resize the workspace and find help

Drag the dividers between variants, board preview, component table and file review to enlarge the information you are checking. The comparison and staging workflow remains unchanged.

Open [offline help](help.html) for the workflow and troubleshooting. See [readable windows, panels and tables](../docs/UI_ACCESSIBILITY.md) for resizing, complete-row reading and keyboard controls.

## Implemented methods, identity and transaction evidence

| Method | Inputs and result | Implementation and limits |
|---|---|---|
| Strict native parsing | Saved project JSON and schematic S-expressions become base symbol/sheet states, named overrides and hierarchy instances. | [`parse_schematic`, `discover_hierarchy`](wayri_variants/engine.py). Unknown variant structures that cannot round-trip safely are refused. This parser implements the supported KiCad 10 representation; it is not a general future-format migrator. |
| Stable object identity | Objects are keyed by project-relative sheet file, kind, native UUID, project name and hierarchy instance path rather than reference alone. | [`object_key`, `snapshot`](wayri_variants/service.py). This survives reannotation and separates reused-sheet occurrences; duplicate identities stop the snapshot. |
| Effective-state comparison | Base state is overlaid with the selected instance's named variant flags/fields, then exact states are compared per identity. | [`_effective_state`, `compare_variants`](wayri_variants/engine.py) and [`_rows`](wayri_variants/service.py). Parent-sheet exclusion is reported separately; comparison does not update PCB geometry. |
| Reviewed transformation planning | Create, duplicate, rename, delete, merge, swap, promote, cleanup, restore and bulk edit operate on an in-memory source map and produce exact candidate bytes plus a diff. | [`preview`](wayri_variants/service.py) and the planning functions in [`engine.py`](wayri_variants/engine.py). Conflicting promotion of reused serialized objects, identity edits and unsafe shared-project rewrites are refused. |
| Targeted text rewrite | Token spans are replaced/inserted while preserving unrelated text and line endings; project metadata is rendered from validated JSON. | [`_apply_edits`, `_desired_base_edits`, `_render_variant`](wayri_variants/engine.py). It is a structural rewrite of supported tokens, not format-wide pretty-printing. Backend regressions are in [`test_backend.py`](tests/test_backend.py). |
| Verified semantic/source backup | A `.wvariants.zip` contains source bytes, a semantic snapshot and a manifest with root UUID, sizes and SHA-256 hashes; validation occurs without extraction. | [`_write_backup`, `read_backup`](wayri_variants/service.py). ZIP/path/duplicate/symlink/size checks protect restore intake. SHA-256 provides integrity, not a trusted signature. |
| Guarded multi-file apply | The reviewed candidate is sealed, source hashes and editor-closure acknowledgement are checked, a recovery backup is made, and each file is atomically replaced and verified. | [`apply`](wayri_variants/service.py). Failures attempt conservative rollback without overwriting a concurrently changed file. The batch is not power-failure atomic. Native/UI coverage and remaining host limitations are recorded in [`VALIDATION.md`](VALIDATION.md), [`test_native.py`](tests/test_native.py) and [`test_ui.py`](tests/test_ui.py). |
| Variant-only restore | Backup identities/topology and field schema must match the current project before selected definitions are restored; full-source restore is a separate destructive recovery plan. | [`plan_restore_variants`, `plan_restore_sources`](wayri_variants/service.py). Variant-only restore deliberately does not restore drawing geometry or silently add/remove properties. |

### Technical background

- KiCad's official [schematic file format](https://dev-docs.kicad.org/en/file-formats/sexpr-schematic/) defines UUID-based hierarchy instance paths used in identity and reused-sheet handling.
- Python's [`zipfile`](https://docs.python.org/3/library/zipfile.html) and [`hashlib`](https://docs.python.org/3/library/hashlib.html) document the archive and SHA-256 primitives. The transaction, semantic snapshot and refusal policies are project methods described above.
