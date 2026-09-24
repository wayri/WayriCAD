# KiCad 10 local integration check — 2026-09-24

Environment: Windows, KiCad 10.0.6, KiCad Python 3.11.5. Source tests also used the local Python 3.14 environment. This is a local development install of 16 independently built PCM packages, not a published 3.3.0 release.

## Reproduction and evidence

- Built all 16 packages with `python build_pcm.py --output-dir .validation/candidate-pcm-20260924-final`. Candidate archives passed IPC schema, entrypoint, icon-size, Python compilation, menu/version bridge, and ZIP integrity checks.
- Installed the 16 candidates using `python tools/install_suite.py --archive-dir .validation/candidate-pcm-20260924-final --apply`. Existing copies were backed up by the installer. Every installed package payload file matched its candidate archive byte for byte.
- KiCad's native Python imported all 16 installed package initializers and registered 17 menu actions (16 tools plus **WayriCAD — All tools…**) in an offscreen wx app. It also imported all 14 installed native tool classes, including Embed3D.
- BOM Studio's packaged `.ico` loaded and was accepted by a native wx frame. Its local favicon route passed the BOM launch test; taskbar appearance in a running editor was not visually inspected.
- Source checks passed: root suite 311 passed / 67 skipped; Constraint Studio 323 passed / 11 skipped; Quick SI 47 passed / 3 skipped; BOM Studio 1,230 passed / 2 skipped; Mechanical Check 31 passed; planar magnetics 57 passed / 2 skipped; manufacturing 14 passed; native heater preview 6 passed. The BOM analytics browser check passed in headless Edge. Documentation source validation passed.
- The heater preview image [shows the copper after the paint-order fix](images/heater-preview-after.png), rendered offscreen from a synthetic 80 × 50 mm heater with a central heating region. It contains no user PCB or project data.
- The [motor winding projection](images/motor-annular-preview.png) was rendered from the built-in synthetic 36-slot, 4-pole, 3-phase preset using KiCad's native Python/wx and Matplotlib. It shows phase and slot assignment, not routed PCB copper or a validated motor layout.

## Follow-up launch audit

- The reported `wxWidgets Debug Alert: python.exe - Application Error` was traced by process ID and parent command line to two disposable standalone native probes started during this audit: an Embed3D dialog probe and a Quick PI close/reopen probe. Both were stopped. They were not PCB Editor processes and used a synthetic fixture. Immediate frame destruction during standalone wx interpreter shutdown is not a valid proof of installed-plugin reliability; subsequent probes use an event loop and suppress OS crash dialogs in owned workers.
- Fixed repeat-open registration failures in the shared launcher: electrical analysis frames now import through a synthetic package namespace, and Copper Balancer's menu bridge avoids its nested legacy registration initializer. Quick PI now ignores deferred inspection after closing, and Constraint Studio cancels its startup watchdog when its window is destroyed. Embed3D and standalone Constraint Studio consume parsed command-line arguments before wx starts.
- Rebuilt all 16 ZIPs from current source into `.validation/candidate-pcm-20260924-audit`, validated the KiCad IPC schema, package structure, entrypoints, icons and Python syntax, then installed them over the KiCad 10 PCM copies with backups. All 1,274 installed payload files matched the validated ZIPs byte for byte.
- A live KiCad 10.0.6 run with two private, disposable PCB Editors passed distinct IPC socket/token checks and five reconnections per editor. From the candidate ZIPs, Fanout Generator opened and produced a nonempty preview, and two Extract Pins instances opened with four pin rows and loaded all three SVG WebView previews. Fixture board bytes were unchanged; all owned editors and workers stopped. This check used the existing prepared KiCad-compatible private runtime. Passing the base KiCad Python instead caused a test-harness relaunch timeout; the disposable processes were cleaned up before rerunning.
- The installed legacy menu bridge opened and closed twice for Bulk Label Editor, Fanout Generator, Via Stitching, Trace RLC / Impedance Analyzer, and Copper Balancer in KiCad's native Python on a disposable saved board. The test board remained byte-identical. This checks actual installed menu action delegates, but runs them in a standalone wx host rather than clicking the existing user's PCB Editor menu.
- A further candidate-ZIP run opened the first windows for Embed3D, Harness and Cable Workbench, Heater Designer, Manufacturing Readiness Manager, Planar Magnetics, and Constraint Studio against the first disposable live editor; each worker exited successfully and the fixture board stayed unchanged. The overall two-editor run failed afterward because KiCad canceled opening its second disposable PCB (`Open canceled by user`), displaying an unwanted native dialog. That failure does not negate the six first-window results, but it is not a passing two-editor run. Subsequent plugin-only checks use one editor and put disposable fixtures under a `WayriCAD-validation` temporary directory rather than the checkout folder.
- Rebuilt the final local candidate as `.validation/candidate-pcm-20260924-branded` after correcting source branding, validated it, and updated all 16 installed PCM copies with backups. All 1,274 installed payload files match this final candidate. The repo README, package search keywords, and BOM third-party notice now use WayriCAD. Historical copyright attribution in two LICENSE files and a stored old test log were preserved; the current checkout folder is still named `kiWay` and is outside product UI naming.
- Current-source checks: root suite 314 passed / 67 skipped / 1 deselected; the deselected subprocess test failed under the local Python 3.14 harness because Windows `DuplicateHandle` returned invalid handle, then both tests in that file passed under KiCad Python 3.11. BOM Studio 1,230 passed / 2 skipped; Constraint Studio 325 passed / 11 skipped; Quick SI 47 passed / 3 skipped; planar magnetics 52 tests passed / 2 skipped. Candidate package and source documentation validation passed.

## Marble project audit (same day)

The saved Marble project was opened in a separate KiCad 10.0.6 project manager and PCB Editor process. The user's existing editor and its unsaved board were left alone. The bounded operation suite ran on Marble for all 16 plugins: 5 `PASS`, 11 `LIMITED`, 0 blocked. Its source-hash check confirms the project files were unchanged. `LIMITED` means an actual operation completed but did not prove the full engineering workflow (for example, a read-only inventory, a geometry preview, or a reduced-order analysis).

| Plugin | Marble operation | First window check |
|---|---|---|
| BOM Studio | Hierarchical BOM inventory; limited by legacy schematic syntax | Installed desktop process on Marble, HTTP 200 after about 29 seconds |
| Bulk Label Editor | Three values previewed, applied and undone on an in-memory Marble copy | Installed menu delegate on Marble, twice |
| Copper Balancer | Bounded F.Cu candidate preview | Installed menu delegate on Marble, twice |
| Embed3D | Read-only model inventory; external model gaps retained | Candidate KiCad IPC action on disposable Marble copy |
| Extract Pins | `J*` extraction: 24 components, 371 pins, 14 shared nets | Installed native window on Marble; two concurrent candidate IPC windows rendered all three SVG diagrams on private fixture |
| Fanout Generator | Bounded escape preview | Installed menu delegate on Marble, twice; candidate IPC preview on private fixture |
| Harness and Cable Workbench | Single-board connector connectivity report | Candidate KiCad IPC action on disposable Marble copy |
| PCB / Foil Heater Designer | Generated preview and reduced-order thermal estimate from Marble dimensions | Candidate KiCad IPC action on disposable Marble copy |
| Manufacturing Readiness Manager | Fabrication metrics against default profile | Candidate KiCad IPC action on disposable Marble copy |
| Mechanical Check | Same-side envelope screening; exact solids not run | Installed native window on Marble |
| Planar Magnetics | Generated coil analysis from Marble dimensions | Candidate KiCad IPC action on disposable Marble copy |
| Constraint Studio | Protocol detection and idempotent rules export | Candidate KiCad IPC visual workspace loaded and completed its native messaging handshake on disposable Marble copy in an unrestricted local run |
| Quick PI | Pad/rail/ground decoupling heuristic | Installed native window on Marble |
| Quick SI | Impedance, return-path and test-point extraction on a routed Marble net | Installed native window on Marble |
| Trace RLC / Impedance Analyzer | Routed-net RLC and layer-following analysis | Installed menu delegate on Marble, twice |
| Via Stitching | Bounded stitching candidate preview | Installed menu delegate on Marble, twice |

The final local candidate was rebuilt and validated as 16 independent PCM ZIPs, then installed in KiCad 10 with backups. A read-only comparison found all 1,276 installed payload files byte-identical to the final candidate ZIPs. Extract Pins switched its embedded diagrams to native SVG rendering because WebView2 navigation failed in the earlier smoke test; the installed Marble window and the candidate's two concurrent IPC windows passed. The native window probe used a disposable KiCad Python host. Several such probes emit wx cleanup diagnostics when that host is terminated, so the result is a first-window check, not evidence that close/reopen is error-free in a long-running PCB Editor. The live IPC fixture and disposable Marble-copy checks passed, and the owned boards were unchanged.

This audit does **not** prove all 16 complete UI workflows on Marble: every plugin completed a Marble-based operation and opened a first window, but six IPC windows used a disposable copy of Marble rather than the original editor, and the computer-control surface could not attach to the separately launched Marble editor for a human-style click-through. Constraint Studio's WebView2 reported `CONNECTION_ABORTED` only in sandboxed runs; the same packaged visual page loaded and completed its `snapshot` native-message handshake on both the small fixture and Marble outside the sandbox. A deferred-navigation experiment did not fix the sandboxed run and was reverted. The BOM desktop took about 29 seconds to initialize on the large Marble schematic; the 12-second diagnostic stack was a slow-load trace, not an observed crash. Neither exact 3D model resolution nor board writes were asserted.

The additional Constraint Studio visual-routing smoke passed under the prepared KiCad-compatible Python runtime: protocol tabs, grouped net selection, dimension-changing preview, width estimator, native rule staging and undo. The same source smoke timed out under the machine's default Python 3.14 WebView2 host, including outside the file sandbox; that host is not the installed runtime. No saved Marble board was changed by this smoke.

## Live Constraint Studio routing check (same day)

On Windows with KiCad 10.0.6, a disposable two-layer D4 board was opened in
PCB Editor. An exact-net Constraint Studio rule set specified 0.20 mm on F.Cu
and 0.30 mm on B.Cu. Starting an F.Cu route displayed “from rule D4 interactive
test / F.Cu” at 0.20 mm. After placing a via, starting a B.Cu route with
KiCad's **Auto track width** toolbar option enabled inherited the existing
0.20 mm segment; saved B.Cu tracks were 0.20 mm. With the option disabled,
starting a new B.Cu route from that via displayed “from rule D4 interactive
test / B.Cu” at 0.30 mm, and saved B.Cu tracks were 0.30 mm. A separate
netclass-assigned native tuning-profile fixture gave the same 0.20/0.30 mm
result with Auto track width disabled. Widths and layers were read back from
the saved fixture boards with `pcbnew`.

The route tools did not change width within one active route after a layer
transition. The user must finish at the via and start a new route on the
destination layer, with Auto track width off. This is native KiCad router
behavior and remains so while Studio is closed. Live differential-pair gap
switching at a via was not visually verified here; rule generation, native DRC
acceptance and persistence have separate checks. These routing fixtures are
disposable and contain no Marble project changes.

## Scope limits

These checks establish packaging, imports, offline UI rendering, source behavior, and the specific live Fanout Generator / Extract Pins IPC workflows above. They do not establish a completed click-through for every plugin in a running PCB Editor after restart. KiCad must be restarted before an already-open editor loads the newly installed menu registrations.

The locally installed SPIKE 0.1.6.0 package provides a compiled `spike_core` PEEC interface but no `ThermalSolver` attribute, even in its Python 3.12 environment. The heater therefore still uses its labeled reduced-order steady-state estimate; SPIKE thermal coupling is not claimed.

Mechanical's nozzle diagram is an illustrative screening envelope, not a measured tool model. Click-to-schematic cross-selection and advanced manufactured PCB motor winding topologies remain outside the validation above. The annular motor view does not add lap-winding or axial-flux physics.

The new manufacturing check measures straight routed track and ordinary via copper against a single closed straight Edge.Cuts outline. Incomplete outlines, unsupported edge shapes, or routed arcs produce UNKNOWN unless an exact violation already proves FAIL. Pads and zone fills remain KiCad DRC's responsibility; this focused check is not a complete DFM review.

## 3.4.0 candidate installation check

After the final changes, the 16 version 3.4.0 PCM ZIPs were rebuilt and passed `tools/validate_packages.py`. The complete candidate was installed into the KiCad 10 user plugin directory with backups. A read-only payload comparison found 1,277 installed files identical to the candidate ZIPs. The public PCM feed still points to published 3.3.0.

The installed Trace RLC / Impedance Analyzer opened on a saved Marble copy, analyzed a routed path, produced a 41-point AC sweep, cleared stale results on refresh, and reanalyzed without changing the board. Its result remained explicitly partial because the reference geometry was unresolved. The installed BOM Studio toolbar entrypoint opened the Marble project in the managed runtime and reached desktop readiness with its local page returning HTTP 200. This caught and fixed a Windows KiCad host issue where inherited console handles caused the managed GUI process to exit before opening; the shared runtime launcher now supplies valid standard handles. The BOM startup test waits for a complete readiness file to avoid treating an in-progress JSON write as a plugin failure.

Final root source suite: 316 passed, 67 skipped and 136 subtests passed, excluding `tests/test_package_contents.py` under the local Python 3.14 subprocess environment; that file's two cases passed separately under KiCad Python 3.11. Source documentation and all 16 candidate packages validated. The skipped tests are not counted as passes. These checks establish local installation and the specified Marble workflows, but do not establish a full interactive click-through of every installed plugin after an editor restart.
