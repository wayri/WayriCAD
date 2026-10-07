# Variant Manager validation

Validated on Windows with KiCad 10.0.6 bundled Python 3.11 and wxPython, October 2026.

- Nine backend regressions cover batch operations, verified backups/restore, merge conflicts, Default retention, stale sources, locks, candidate mutation, identity restrictions, unknown variant tokens and distinct reused-sheet occurrences.
- Native hierarchical fixture: create, edit, duplicate and promote; KiCad netlist and PDF export accepts transformed root/child files. Named BOM exports verify 22k+DNP versus retained 10k+populated states. PCB bytes remain unchanged.
- Native wx test: compare values/flags; cross-selection; full staged-change rows; project-change invalidation; preview and table remain separate and usable at 1360×900 and 1000×800. The shipped capture uses this generated fixture and displays a generic project path. Only the test window is captured.

These checks cover saved-file transformations and a standalone native window. They are not evidence of native GUI testing on Linux/macOS or an interactive workflow attached to every KiCad editor version. PCM installation/isolated import checks are recorded in the release audit when performed.
