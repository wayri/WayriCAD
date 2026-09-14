# Variant Workbench Tcl/Tk validation

The current execution environment could import tkinter but could not initialize Tcl. This is a validation limitation; it does not establish that these installations fail when launched outside the restricted host.

| Interpreter | Tcl DLL version | Resource requirement |
| --- | --- | --- |
| Python 3.11.9, Local/Programs/Python/Python311 | 8.6.12 | init.tcl requires exactly 8.6.12 |
| Python 3.14.2, Local/Python/pythoncore-3.14-64 | 8.6.15 | init.tcl requires exactly 8.6.15 |

Both installations contain readable `tcl/tcl8.6/init.tcl` and `tcl/tk8.6/tk.tcl` files. Matching child-only TCL_LIBRARY/TK_LIBRARY values and removal of inherited Python/Tcl overrides did not resolve initialization. No user installation or persistent environment was changed.

A direct Tcl 8.6.12 DLL probe returned `0` for `file exists` on the same absolute init.tcl path that Python and PowerShell could read. Tcl `source` returned “no such file or directory”. This points to Tcl filesystem visibility in this execution environment, rather than mismatched resource versions.

The launcher now validates `tkinter.Tcl()` instead of only importing tkinter. It skips unusable runtimes and reports an actionable error rather than launching a process that exits before showing its window. Fresh Variant GUI capture remains unverified here; the other 16 wx plugin captures completed. Runtime selection can be overridden with WAYRICAD_VARIANT_PYTHON.
