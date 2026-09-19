# WayriCAD Constraint Studio 3.1.1

Constraint Studio 0.3.1 is integrated into the existing Protocol Constraint Composer package. Its package ID stays `com.github.wayri.wayricad.protocol-constraints`; it uses the suite's IPC launcher and wx runtime. It edits a saved project snapshot, not the live board. Save the board and Board Setup before opening it.

The **Visual overview** shows enabled rules, local errors/warnings and changed files. Select a rule to see a pan/zoom scope map: blue means its condition matches, amber means native evaluation is needed, gray means no match. Click an item for details; double-click a rule to edit it. Dashed region outlines show supported linear rule areas. Pad glyphs and curved tracks are simplified; complex region outlines remain in native review. Scope colours are not DRC violations or effective-rule certification.

**Protocol presets** retains USB, CAN, Ethernet, PCIe/SerDes, DDR, RS-485 and RF detection. Preview and **Stage in Constraint Studio** merge the managed block into the workspace, preserving other rules. Geometry and assignment changes invalidate the old preview. The other pages provide constraint worksheets, BGA regions, clearance matrices, netclasses, board settings, reusable sets, timing, engineering tools and DRC evidence.

**Review & export** shows local lint, file diffs and generated native rules. Export to a separate empty folder, run native DRC on that copy, and use its **Apply Review** helper after closing every source-project editor. Hash checks and backups protect the offline apply. The old direct-write Apply button is replaced by staging. Review exports include the helper's GPL license.

Open Help/F1 for the bundled reference, or read [the original development guide](docs/USER_GUIDE.md). Installation instructions in that original guide describe the standalone development package; use the WayriCAD package for this integration. Do not install the original Constraint Studio PCM beside it.

Source launch, with KiCad's Python (wxPython required):

```powershell
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m protocol_constraint_composer_plugin.studio_ui path/to/board.kicad_pcb
```

The source owner authorized GPL-3.0 inclusion; archive hashes and the original delivery notice are retained in `SOURCE_PROVENANCE.json` and `constraint_studio/LICENSE.original.txt`. Signing still requires optional `cryptography`; NumPy accelerates the optional solver. Neither is installed automatically.

Validation and remaining acceptance work are recorded in [the integration report](docs/INTEGRATION.md). Full KiCad host/PCM/DPI acceptance and KiCad 11 remain unverified.

Preset geometry is illustrative and must be replaced with values derived from the actual stackup, protocol specification, device requirements and fabricator. Always use KiCad's rule syntax checker and DRC after applying rules.


## Native interface

![Native WayriCAD Constraint Studio visual overview](help-workflow.png)

The staged overview shows rules, local lint and a scope map for a saved example board. Scope colours describe condition matching, not native DRC acceptance. Review the exported changes before offline apply.

The installed package includes [offline help](help.html) with its workflow and limitations.
