# WayriCAD Embed3D 0.4.1 — blank Scan hotfix

## Identified defect

Version 0.4.0 used the following table setup sequence:

```python
self.model = ComponentModel(self.selection_changed)
self.table.AssociateModel(self.model)
self.model.DecRef()  # Wrong for wxPython Phoenix.
```

The Phoenix Python wrapper already performs the initial native-reference release when a Python-owned model is associated with a view. The last call therefore releases the reference that the view still needs. The result can be a deleted native model, failed table refresh, blank component list, or a native crash. Keeping a Python variable pointing at that wrapper does not restore its deleted C++ object.

0.4.1 uses `attach_component_model()` to construct and associate the model exactly once, without a second reference-count adjustment. The window keeps a Python reference for selection/filter access; native ownership stays with the view. No migration of the PCB or schematic is required.

This is a confirmed source-code defect and is reproduced by the new reference-count test double. We have **not** run the user's installation or received its diagnostic log, so this does not prove it is the only cause of that particular blank scan.

## Scan behaviour

- Scanning discovers all components in the selected saved files, independent of global or per-component selection. Checkboxes choose assets for the operation; they do not suppress the component list.
- PCB-only scanning discovers footprints and linked model entries. A schematic is required only for symbol discovery.
- Footprints without a model remain visible, with an unavailable 3D cell. Missing model files remain visible and need repair before model embedding.
- A successful scan reports its component count. An empty saved design and a nonmatching search have distinct messages. Clear the search to reveal filtered rows.
- Source/read/parser/view-refresh failures show an error instead of a misleading Ready status. Old rows, if present, are locked and cannot be used for a design operation after a failed scan.
- Sources are saved files, not unsaved editor buffers. Saving and rescanning is still required after design edits. A selected invalid schematic is not silently ignored; fix or clear its source field to deliberately work PCB-only.

## Install the fix

Close the PCB Editor, install `WayriCAD Embed3D-0.4.1-PCM.zip` unchanged through Plugin and Content Manager's Install from File, then restart the editor. Remove only the older WayriCAD Embed3D entry first if PCM refuses replacement. Do not leave both PCM and manually installed copies.

The title must read **WayriCAD Embed3D 0.4.1 · Design assets**. Open the saved populated PCB, launch the plugin, and check the Saved PCB path. Scan should report components before you change any asset checkbox. Select the root schematic as well when symbol operations are needed.

## Diagnostics after a remaining failure

Use **Options & library tools → Save scan diagnostics…**. This works even when no preview exists and Scan failed. It records plugin version and loaded source module path, KiCad/wx/Python versions, source paths, scan count/outcome, filter text, and the error traceback. It excludes design contents, 3D payloads and the full process environment. Nothing is uploaded. Review local paths before sharing.

The ordinary rotating log is still at `%LOCALAPPDATA%\WayriCAD Embed3D\embed_3d_plugin.log` on Windows, or the log path displayed in diagnostics.

## Tests and limits

The new headless controller tests exercise the real saved-file parser and Python scan thread, while explicitly substituting the wx controls/event queue. The ownership double reproduces Phoenix's reference-transfer sequence: the old extra release deletes the model, and the corrected association retains it. Package validation rejects a manual `DecRef` call in the workspace module.

These tests do not constitute native Windows, wx drawing, or KiCad-host execution. Three additional opt-in native tests check model lifetime, native child enumeration after Reset, and a threaded fixture scan into a real wx control; they were skipped here because wxPython is unavailable. All previous embedding/unbundling/relinking regression tests were also rerun. See `TEST_REPORT.md`.

## Primary implementation references

Reviewed 10 September 2026:

- wxPython Phoenix 4.2.3's `AssociateModel` wrapper and initial-reference release: https://raw.githubusercontent.com/wxWidgets/Phoenix/wxPython-4.2.3/etg/dataview.py (AssociateModel block).
- wxPython model/view ownership documentation: https://docs.wxpython.org/wx.dataview.DataViewCtrl.html#wx.dataview.DataViewCtrl.AssociateModel
- Index-list Reset contract: https://docs.wxpython.org/wx.dataview.DataViewIndexListModel.html
- KiCad addon package layout: https://dev-docs.kicad.org/en/addons/index.html
