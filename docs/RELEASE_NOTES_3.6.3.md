# WayriCAD 3.6.3 release notes

This patch corrects failures reported after 3.6.2 on KiCad 10 for Windows.

- The shared launcher skips KiCad's GUI executable when looking for a Python
  runtime. Probing that executable with Python's `-I` option produced the
  “Unknown option 'I'” dialog and opened another KiCad window. The launcher
  now tests Python executables only.
- Quick PI imports `math` for its input checks. Selecting a net, source and
  sink and pressing **Run analysis** no longer stops at `name 'math' is not
  defined`. Other analysis errors remain visible in the status and console.
- The Quick PI console starts folded and the chart uses more of its plot area.
  Quick SI keeps its results table compact so the route preview gets more
  vertical space. The controls can still be expanded or the window resized.
- QuickTherm now starts with a compact, guided setup. When a board has no saved
  power or thermal-resistance fields, enter explicit values for selected parts
  in the window and run without editing the PCB. Results and reports identify
  those values as user-entered assumptions; the board preview fits the window.
- Every independent package registers its own PCB Editor toolbar button through
  the legacy action API. **WayriCAD — All tools…** remains available in the
  External Plugins menu on displays where KiCad clips its flat action list.
- Embed3D opens a selective workspace by default. Scan the saved design, check
  component assets, then preview **Embed + relink** or **Unwind to local
  folder** before applying. The previous full-project localization, backup
  workflow and other asset operations remain under Options. Unwind targets a
  unique subfolder under the project's `local/` directory.
- Bulk Label Editor skips graphical board shapes when listing editable text.
  Fanout and Via Stitching read curved filled-copper boundaries through a
  bounded polygon tessellation path. Constraint Studio keeps its native
  worksheet visible while the optional embedded browser starts.
- Pin Extractor filters saved-board footprint listings by the requested
  reference pattern and displays readable KiCad library IDs. Saved-board
  Quick PI and QuickTherm runs use the scientific runtime without requiring
  KiCad's IPC package when a PCB path is already supplied.
- BOM Studio's local browser fallback uses KiCad's bundled wx file picker to
  open a project when the embedded browser cannot start.
- Manufacturing Readiness compares saved and live boards while ignoring only
  transient KiCad footprint header metadata. It still requires every design
  token to match and retains exact saved-file hashes for release checks.

Update each installed WayriCAD package to 3.6.3 in Plugin and Content Manager,
including QuickTherm as an independent package, then restart PCB Editor. An
installed QuickTherm copy showing version `0.0` or `3.6.0` is an older package
and will not be updated by updating Quick PI alone.

Validation covers the shared test suite, independent package and wheel checks,
and offline KiCad 10.0.6 windows and board actions on Windows. A running editor
on every supported OS has not been tested.
