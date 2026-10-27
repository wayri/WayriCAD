# WayriCAD 3.6.37

Bulk Label Editor now finds PCB nets and IPC board text instead of opening an
empty example-filtered view.

- Fresh net names, pad/track/via/zone counts and connected reference.pad terminals.
  Substring, wildcard and fuzzy search; multiple-net PCB selection; CSV export.
- Blank Find starts with the text inventory. IPC wrappers are classified as text;
  shapes are skipped. Footprint text is included; built-in fields are not duplicated.
- Apply all changes or selected rows after sorting. Selected-footprint scope uses
  UUID ownership. Values/custom fields start disabled.
- Invalid rules, blank replacements, new duplicate references and stale objects
  stop the batch. Fresh readback checks writes; failures attempt recovery.
  Session Undo/Redo is retained.
- Virtual tables, compiled rules and debounced typing keep browsing responsive.
  CLI adds saved-board nets inventory/search and string preview. Existing JSON
  request clients remain supported.

Electrical net names remain read-only. Rename electrical labels in Schematic
Editor, then Update PCB from Schematic. Drawing-text edits do not rename nets.
The release adds no schematic-editor action. Restart KiCad after updating.

See [validation evidence and limits](audits/RELEASE_3.6.37.md).
