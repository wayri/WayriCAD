# QuickTherm reliability validation

Local checks on Windows: 298 QuickTherm tests passed, 29 environment-gated
skips, 221 subtests. Focused solver/contact/CLI checks: 48 passed, 3 skipped.
KiCad 10.0.6 native UI: four tests passed, including automatic source inclusion,
stale export invalidation, asynchronous Run and ordinary window close.

The simple public-board power/ambient check converged with 0.75 W input and
2.22e-16 W heat-balance residual, without modifying the source. Junction values
remain unknown without package data. This is not measured thermal accuracy.

The official Windows CalculiX 2.23 static solver passed its actual launch check
and the Gmsh uniform-plate analytical conduction test in an existing research
runtime. Reproduce with `WAYRICAD_TEST_CCX` pointing to the executable and run
`python -m unittest quick_therm_plugin.tests.test_thermal_calculix.CalculixBridgeTests.test_real_calculix_uniform_plate`.

Run native workflow checks with KiCad Python:
`python -m unittest quick_therm_plugin.tests.test_whole_board_ui -v` and
`python tools/verify_quick_therm_quick_start.py --worker-python "C:/Program Files/KiCad/10.0/bin/python.exe"`.

Contact regressions verify conservation and conflicting-temperature rejection
in both kernels. Linear tests cover a coupled network, singular/nonfinite
inputs and analytical temperatures across 36 orders of conductance.
The user's screenshot board was not reproduced from native project data.
Hosted CI and final artifacts require separate release validation.
