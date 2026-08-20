# KiWay Bulk Label Editor 0.7.1

Bulk Label Editor performs reviewed, pattern-based renaming of supported KiCad
objects. It is intended for channel, interface, rail, connector, and repeated
hierarchy naming changes where manual editing would be slow or inconsistent.

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

## Limitations

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

See help.html for the annotated screenshot and integrated walkthrough.
