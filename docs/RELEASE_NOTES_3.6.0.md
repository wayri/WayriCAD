# WayriCAD 3.6.0 release notes

QuickTherm is now an independently installable KiCad plugin with its own toolbar action, icon, native window, PCM archive and command-line entry point. Quick PI retains electrical analysis; its former thermal action and implementation have moved to QuickTherm.

QuickTherm expands the saved-board thermal review with a resizable board viewport, top and bottom component maps, an optional declared-input board-temperature overlay, virtual temperature probes, and a sortable component table. Saved footprint properties can be mapped to dissipation, RθJA, RθJB, RθJC, minimum junction temperature and maximum junction temperature. Per-part limit checks report PASS, FAIL or UNKNOWN, and the CLI can return a nonzero status when a limit fails or is unresolved. HTML and JSON reports include probe and limit evidence. A `thermal` job preset can run the same reviewed configuration from the WayriCAD CLI or a KiCad jobset.

The [QuickTherm guide](../quick_therm_plugin/QUICK_THERM_USER_GUIDE.md) includes a reproducible [saved-board example](../quick_therm_plugin/examples/thermal-demo.kicad_pcb), [configuration](../quick_therm_plugin/examples/thermal-demo-config.json), [report](../quick_therm_plugin/examples/thermal-demo-report.html) and native-window screenshots. The example uses hypothetical component and material values. QuickTherm remains a steady-state screening tool; its board views are approximations, not CFD or coupled electrothermal simulation.

Source validation covered QuickTherm's focused tests, KiCad 10.0.6 native-Python execution of the public example, isolated wheel imports, and all 17 disposable PCM archives. Published package availability and installation in a running KiCad editor require separate release and installation checks.
