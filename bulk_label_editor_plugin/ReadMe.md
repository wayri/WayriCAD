# WayriCAD Bulk Label Editor

<img src="resources/icon-96.png" width="96" height="96" alt="Bulk Label Editor icon">

Browse PCB text and nets, preview bulk text changes, and apply the rows you reviewed.

| Start here | Link |
|---|---|
| Install or update | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation](../docs/INSTALLATION.md) |
| First use | [Workflow](#workflow) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| CLI | [Saved-board inventory and rename preview](#command-line) |

## Interface

![Earlier native text-review window](help-workflow.png)

Earlier native text-review capture, retained for reference. Version 3.6.37 adds
the net browser and the revised controls described below.

## What it can do

| Workspace | Features |
|---|---|
| Text and rename preview | References, values, custom footprint fields, board text and footprint graphical text; wildcard or regex replacement; selected-footprint scope; apply all changes or selected rows; session Undo/Redo. |
| Nets and connections | Fresh PCB net names, pad/track/via/zone counts and `reference.pad` connections; substring, wildcard or fuzzy search; multiple-net selection on the PCB; copy names and export CSV. |
| Review tables | Sort columns, select multiple rows with Ctrl/Shift, locate objects by double-click, and export the visible table. Virtual rows keep large inventories inexpensive to display. |

**Electrical nets are read-only.** A PCB drawing string and an electrical net name
are different objects. Rename electrical labels in Schematic Editor, then use
**Update PCB from Schematic**. This release does not add a schematic-editor action
or silently reassign copper to other nets. PCB reference/value edits also do not
update the schematic automatically.

## Workflow

1. Open the intended PCB and launch Bulk Label Editor. The initial blank find
   rule shows loaded references and PCB text; no rename is armed.
2. Use **Nets and connections** to find a net and see its pads and copper counts.
   Search `clock`, `BUS[*]`, or `~clok` for literal, wildcard or fuzzy matching.
   Select several rows and choose **Select nets on PCB** to replace the previous
   selection with only those nets' pads, tracks, vias and zones. Unused named
   nets remain listed even when they have no selectable copper.
3. For text changes, open **Text and rename preview**. Enable only the intended
   scopes. Values and custom fields start disabled. **Selected footprints only**
   excludes free board text and unselected footprints, using UUID ownership even
   if two footprints currently have the same reference.
4. Enter the find/replacement rule. Inspect old/new text. Blank **New** cells in
   the initial inventory mean unchanged. Changing the rule disables Apply until
   its new preview is ready.
5. Choose **Apply all changes**, or Ctrl/Shift-select changed rows and choose
   **Apply selected rows**. Use this window's **Undo** or **Redo** for the batch.
   Check the PCB, then save in KiCad. Closing the window discards session history.

| Mode | Find | Replace | Example |
|---|---|---|---|
| Wildcard, whole field | `CH*_MAIN` | `PORT*_MAIN` | `CH12_MAIN` → `PORT12_MAIN` |
| Wildcard character | `CH?_MAIN` | `CH?_REDUNDANT` | `CH2_MAIN` → `CH2_REDUNDANT` |
| Regex | `^R(\d+)$` | `X\1` | `R12` → `X12` |

Wildcard bus brackets are literal. Replacement `*` and `?` tokens consume
captures of the same kind, in order. Captured text is inserted once rather than
being reinterpreted as another wildcard. Regex uses Python replacement syntax.

## Safeguards and troubleshooting

- Refresh reads the originating PCB again, including nets created after launch.
  Failed net reads show an error rather than a misleading zero-net result.
- Preview never writes. Apply resolves identities afresh, checks old text and
  rejects deleted objects, blank text and new duplicate references.
- Writes are checked with fresh reads. A failure triggers recovery; incomplete
  recovery is reported explicitly. This window's batch history is separate from
  persistent editor/project history.
- Shapes are excluded from the text inventory. Built-in reference/value fields
  are not duplicated under the custom-fields scope.
- If a table is empty, inspect the scope, search and status count; clear Find to
  browse text, or clear the net search to browse every named net. Use **Reload
  PCB and nets** after editing in KiCad.
- CSV export creates a new file and neutralizes spreadsheet formula prefixes.
  Neither table export nor the CLI changes the source PCB.

## Command line

Use KiCad's Python for saved-board reading, or select that interpreter through
`wayricad tools run --python`. The suite CLI requires the wheel installation;
an independently installed PCM package also supports its own `cli.py` module.

```text
wayricad tools run bulk-label-editor -- nets C:/Projects/Example/board.kicad_pcb --search "BUS[*]" --output nets.json
wayricad tools run bulk-label-editor -- preview CH1_MAIN CH2_MAIN --find "CH*_MAIN" --replace "PORT*_MAIN"
```

`nets` returns JSON counts, terminals, member UUIDs and the saved source hash.
`preview` needs no KiCad bindings. Existing `--request params.json --output
result.json` data-only automation remains supported. GUI write operations are
not implied by CLI preview. Existing output files are preserved.

## Methods, references and validation

- [Net inventory](inventory.py) uses the originating PCB API and a bounded IPC
  read scope; net names are queried afresh instead of trusting the startup cache.
- [Rules and batch checks](rules.py) compile once per preview, validate the final
  reference set, check stale values and recover failed batches. The UI rereads
  edited fields from the board after writes and recovery.
- [KiCad IPC API](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)
  defines the editor interface; [Python regex syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax)
  defines regex mode. These are interface references, not proof of live acceptance.
- Portable tests cover inventory, refresh, read failures and rule/recovery cases.
  Native tests in `tests/` exercise synthetic KiCad 10 boards and wx windows.
  [Release validation](../docs/audits/RELEASE_3.6.37.md) distinguishes native saved-board,
  controlled IPC-facade and packaged checks from connected editor transactions.
