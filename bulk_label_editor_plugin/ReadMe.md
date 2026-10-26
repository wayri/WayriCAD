# WayriCAD Bulk Label Editor

<img src="resources/icon-96.png" width="96" height="96" alt="WayriCAD Bulk Label Editor icon">

| Start here | Link |
|---|---|
| Download and install | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation guide](../docs/INSTALLATION.md) |
| First use | [Getting started](#workflow) |
| Help | [Offline help](help.html) · [Compatibility](../docs/COMPATIBILITY.md) |
| Command line | `wayricad tools run bulk-label-editor -- --help` |

CLI scope: Data-only rename preview; reviewed writes remain in the GUI. The unified command requires the [suite CLI installation](../docs/TOOL_CLI_CATALOGUE.md); installing this PCM plugin alone does not install the complete CLI suite.

## Capabilities

- Renames PCB text, footprint references, values, and supported fields in bulk.
- Matches names with wildcard `*` and `?` patterns or regular expressions.
- Uses regex capture groups for structured replacements.
- Builds a sortable, reviewed preview before any write.
- Records old and new values in operation history and supports KiCad undo where available.

## Limitations

- Operates on PCB-exposed data and does not write schematic labels.
- Renames do not update firmware, external documentation, test scripts, or manufacturing systems.
- Changing a rule or object scope invalidates the preview and requires regeneration.
- Cross-session undo depends on the edited KiCad object and editor state.

## Overview

Bulk Label Editor performs reviewed, pattern-based renaming of supported KiCad
objects. It is intended for channel, interface, rail, connector, and repeated
hierarchy naming changes where manual editing would be slow or inconsistent.

## Native interface

![Native WayriCAD Bulk Label Editor window](help-workflow.png)

Native rename preview workspace before applying a rule. Review every proposed change before Apply.

The installed package includes [offline help](help.html) with its workflow and limitations.

## Workflow

1. Save the board before beginning.
2. Select the object scopes to inspect.
3. Enter a wildcard or regular-expression find rule and replacement.
4. Build the preview and sort or inspect every proposed change.
5. Apply exactly the reviewed preview.
6. Use the operation history or KiCad undo if the result is not intended.

The plugin can work with PCB text, footprint references, footprint values, and
supported fields. Wildcards support "*" for any sequence and "?" for one
character. Regex mode supports capture groups for structured replacements.

Example:

~~~text
Find:    CH*_MAIN
Replace: CH*_REDUNDANT
~~~

The preview table is the authoritative write set. Changing the rule or object
scope invalidates the previous preview and requires regeneration.

## Safeguards

- No write occurs while building a preview.
- Apply operates only on rows present in the current preview.
- Empty rules and invalid regular expressions are rejected.
- Operation history records the old and new values.
- The plugin does not silently rename schematic labels through the PCB API.

## Detailed limitations

Renaming PCB references, values, or text does not automatically update firmware,
external documentation, test scripts, schematic source data, or manufacturing
systems. Re-run ERC/DRC and project-specific consistency checks after applying a
large rename.

## Troubleshooting

- **No matches:** confirm the enabled object scopes and whether wildcard or
  regex mode is active.
- **Unexpected preview:** narrow the rule before applying; use anchors in regex
  mode when matching the entire value.
- **PCB and schematic differ:** perform the source-of-truth rename in the
  schematic and update the PCB where appropriate.
- **Undo unavailable after restart:** restore from KiCad/project backups or the
  recorded operation details; persistent cross-session undo depends on the
  edited KiCad object and editor state.

See help.html for the current window and integrated walkthrough.

## Implemented methods and evidence

The implementation is deliberately a reviewed text transformation, not a netlist
or schematic refactoring engine.

| Method | Inputs and result | Implementation and applicability |
|---|---|---|
| Editable-object inventory | The saved/open PCB's footprint references, values, supported footprint fields and board text become typed `EditableItem` rows. | [`refresh_items`, `_add_fields` and `_add_board_text`](bulk_label_editor_plugin.py) use the PCB API exposed by the originating editor. Shapes that merely expose a text-like method but cannot return text are skipped. |
| Wildcard matching | A whole-field pattern with `*` and `?` produces one candidate replacement; matching is case-insensitive unless requested. | [`wildcard_replace`](bulk_label_editor_plugin.py) escapes literal characters, turns wildcards into capture groups and substitutes captured `*` groups from left to right. It is not shell glob expansion and `?` captures are not available in the replacement. |
| Regular-expression matching | Python regular-expression search/replacement, including capture-group replacements, produces candidate values. | [`_replace`](bulk_label_editor_plugin.py) delegates to `re.sub`; invalid expressions stop preview. Regex behavior is the Python language behavior, not KiCad rule-expression syntax. |
| Reviewed write set | Preview stores `(object, old value, new value)` rows; Apply writes only that set. | [`on_preview` and `_apply_operation`](bulk_label_editor_plugin.py) re-resolve object identities against a fresh board read before writing. A removed object stops Apply. Changes made to a still-present field after preview are protected by the shared [`apply_fields`](../wayricad_runtime/fields.py) stale-value checks. |
| Session undo/redo and cross-navigation | Successful batches are retained as reversible old/new tuples; a preview row can select its PCB object. | [`on_undo`, `on_redo`](bulk_label_editor_plugin.py) and [`selection_utils.py`](selection_utils.py) operate only in the current window/editor session. This history is not a persistent project transaction log. |

There is currently no plugin-local automated test directory. The implementation
is exercised through the suite's shared field-application and runtime tests, but
that does not substitute for an installed-editor rename/undo check on the target
KiCad version.

### Technical background

- [KiCad IPC API for add-on developers](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/) describes the editor-scoped API boundary used by installed plugins. It is a dependency/interface reference, not evidence that a particular rename is correct.
- [Python regular-expression syntax](https://docs.python.org/3/library/re.html#regular-expression-syntax) defines regex mode. Wildcard mode is the project-specific transformation documented above.
