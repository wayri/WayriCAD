# WayriCAD 3.6.21 validation

## Scope and provenance

Source changes include independent PI/SI studies, explicit return-conduction loops, a PI Joule/temperature-feedback checkbox, offline report review controls, all-tools CLI discovery/dispatch and the previously tested Mechanical Check UI. Numerical capabilities remain bounded to the models described in each guide; no whole-circuit or coupled-bus qualification is asserted.

Windows native environment: KiCad 10.0.6 Python 3.11/wxPython/OpenGL and FreeCAD 1.1. Portable suite uses Python 3.14. Saved-board synthetic fixtures, analytical copper strips and existing regression references were used; no private user board is included.

## Evidence

- SI: 94 native tests run, 93 passed, 1 optional upstream numerical-runtime test skipped. A real two-route board with vias and explicit return terminals exported study JSON/HTML; saved bytes were unchanged. Missing-terminal cases were retained.
- Reports: 49 tests plus 17 subtests passed. Five rendered PI/Therm/SI/study reports passed Chromium checks at 1024×720 for JS errors, overflow, navigation, sorting/filtering, print behavior, thermal cross-selection and child-report links.
- CLI: all 23 backend help commands passed in isolated processes. Unified dispatch/control tests, job-preset validation and Silkscreen source-protection tests passed. The Silkscreen preview ran with actual KiCad geometry and preserved its source; direct-worker overwrite and companion-rule creation are rejected.
- Mechanical Check: 101 regression tests passed, 4 native-outline tests skipped in the system interpreter; separate native Quick 2D / exact 3D and isolated-PCM checks verified camera/filter/selection cleanup, rulers, actual STEP geometry and unchanged source files. See [the Mechanical UI audit](MECHANICAL_REVIEW_UI.md).

- Root suite: 488 passed, 88 skipped, 222 subtests.
- Portable PI: 253 passed, 26 skipped, 210 subtests. Separately, 23 native VTK mesh/multisink tests and 3 native batch/Joule UI tests passed. Actual saved-board cases completed an explicit DC return loop and steady temperature-feedback study, preserving source bytes.
- QuickTherm: 230 passed, 26 skipped, 190 subtests.
- Fresh builds of all 23 independent PCM ZIPs passed package validation. PI and SI native workers were then run from extracted ZIPs with isolated Python paths; PI completed its loop and thermal-feedback cases, SI retained two reported routes and one expected invalid-terminal case.

Exact-source CI and final wheel/public asset checks are release gates; publication identifiers are recorded after verification.

## Screenshot provenance

New report previews `quick_pi_plugin/help-report-review.png`, `quick_therm_plugin/help-report-review.png` and `signal_integrity_advisor_plugin/help-report-review.png` were captured from actually rendered HTML reports generated from synthetic regression fixtures. Deliberately incomplete inputs illustrate honest model/coverage reporting; these are not passed board studies. The screenshots show no personal paths or private projects. No redaction was needed. Existing board/workflow screenshots are retained.

## Release gates and limits

Publish only after the candidate's eight CI jobs, independent package checks and relevant native workflows pass. Publish assets before promoting PCM metadata; verify downloaded bytes and hashes. Native Linux/macOS UI and every DPI/live-editor scenario are not established by portable CI. Skips and optional-runtime gaps remain limitations.
