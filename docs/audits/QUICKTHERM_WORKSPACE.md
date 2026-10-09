# QuickTherm component inputs and interactive workspace validation

The unpublished 3.6.13 candidate replaces the vertically stacked setup/map/results page with a maximized native workspace. Component inputs use a full-width editable table, and the board tab has compact setup and inspection side panels. Scanned saved properties, explicit overrides, checked scope and source provenance remain separate. RθJA/JB/JC and temperature limits are independently editable; filtering does not drop checked hidden rows.

The physical board workflow without virtual heatsinks can run known power with optional RθJB, without also requiring RθJA. The existing independent component and CLI contracts retain their behavior. An explicit `board_power_only` request selects the board-power workflow; model junctions use the computed board site plus declared `power × RθJB`. Missing RθJB leaves the package temperature and limit check unknown. Table overrides reach physical models and per-component temperature limits; clearing a cell masks its scanned value instead of restoring it silently.

Native 2D/3D viewports omit graph axes, while scientific report plots retain units and axes. The 3D renderer preserves saved contours and open cutouts/drills, displays supported cells at their modeled depth, renders one thin-sheet midplane field, and leaves missing cells blank. Selection and hover labels remain bounded. Drag orbit, Shift-pan, wheel zoom and Fit are available. Footprint outlines and temperature markers remain pickable after camera changes. STEP component solids are not loaded. Saved drill snapshots lack depth/span information, so this overview does not reconstruct blind/buried drill geometry. Renderer geometry does not change the thermal solver's masks.

## Checks performed

Windows, KiCad 10.0.6, KiCad Python 3.11.5, wxPython 4.2.2 / wxWidgets 3.3.2, Matplotlib 3.10.8 and NumPy 2.4.2 were used for native checks. Portable tests used Python 3.14.2.

- Shared source tests: **402 passed, 73 skipped**, with 152 passing subtests.
- QuickTherm source tests: **172 passed, 22 skipped**, with 88 passing subtests.
- Focused native table, integrated workspace, labels and 3D renderer tests: **14 passed**, no skips. The workflow reads actual saved fields, commits an active RθJB grid editor, exercises scope/filters, runs the native service, checks `junction − board site = power × RθJB`, tests edited limits, removes the otherwise required RθJA, exercises orbit/Shift-pan/wheel/Fit and verifies the source hash is unchanged. Sidebar dimensions are checked for clipping.
- The renderer worker also ran **46 focused native regressions**, including contour/drill clipping, field support, model depth, selected/hover labels and projected picking. Its native fixture assertion runs in a bounded fresh interpreter to avoid SWIG/wx teardown affecting later tests.
- Current-source PCM build: **19 ZIPs** validated against official schemas, independent runtime/action/icon requirements and Python syntax. No candidate feed was promoted.
- An extracted QuickTherm ZIP loaded its own native window, scanned the public example, edited RθJB, ran a four-source physical model, rendered 3D, found the new help/images and preserved the PCB hash, with the source checkout removed from the import path.
- Current source wheel built successfully; documentation, Python compilation and whitespace checks passed.

The native checks use bounded event yields, synchronous service calls and fresh subprocesses. They do not establish live PCB Editor toolbar/IPC selection acceptance, a full long-running GUI session, installation on other operating systems, or numerical qualification of a user's board. Existing MainLoop/native teardown limitations from the earlier launcher audit were not counted as passes. Skipped portable tests are unavailable native/runtime cases, not verified compatibility.

## Screenshot provenance

`quick_therm_plugin/examples/quicktherm-input-workspace.png`, `quicktherm-board-workspace.png` and `quicktherm-3d-workspace.png` were captured from the native window using the public `thermal-demo.kicad_pcb`. Four hypothetical power sources are checked; two mounting footprints remain excluded. The thin-sheet run uses assumed 35 W/(m·K) effective conductivity, 0.8 emissivity, 10 m/s airflow, saved thickness and a 48-cell long-axis grid. These demonstrate the UI and declared model output, not measurements or validated hardware. Only the public filename appears; no personal path/project data was included or redacted.

The candidate has not been installed, pushed, published or submitted as a PR.
