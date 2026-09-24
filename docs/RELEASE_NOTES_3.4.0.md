# WayriCAD 3.4.0

This release updates the 16 independent KiCad 10 PCM packages. The public PCM feed is promoted only after the tagged source commit, uploaded ZIPs and hashes are verified. Published 3.3.0 assets remain unchanged.

## Changes

- BOM Studio displays a native loading window while it reads large saved projects, then a loading message until its embedded workspace is ready. Analytics now label measured observations and unknowns instead of presenting unsupported plots as insight.
- Constraint Studio retains the staged, reviewable project workflow and adds protocol-specific per-layer routing profiles with selected net groups and native KiCad sizing rules. It now reloads changed saved boards when the clean workspace regains focus, fixing missing two-atom KiCad 10 net names in the layout inspector. Side-by-side stackup and parallel-trace previews respond to width and gap edits. Each profile can also stage a reviewed via type, diameter, drill and layer span as scoped DRC rules; saved netclass via dimensions can be copied into the form. KiCad still requires explicit selection of non-through via types while routing. The native WebView smoke test covered preview changes, via staging, protocol tabs, grouped nets and undo.
- A live KiCad 10.0.6 route/via check confirmed 0.20 mm on F.Cu and 0.30 mm on B.Cu for an exact-net profile and a netclass profile when a new route starts on B.Cu with **Auto track width** off. With that option on, KiCad inherited the F.Cu width on B.Cu. KiCad also retains one width within an active route, so routing must end at the via and restart on the destination layer. The user later confirmed differential-pair layer switching works in their KiCad session; that check was not captured as an automated measurement in this repository.
- The review page now opens the exported offline Apply Review helper directly. After closing the source project's KiCad editors and confirming the helper's review, applying the bundle makes the profile available when the project is reopened. A disposable export/apply/reopen check confirmed both layer widths, the via recipe, native rules and backup creation. KiCad cannot safely reload these project files into an already open PCB Editor.
- Trace RLC / Impedance Analyzer refreshes the board stackup without retaining stale analysis or AC-sweep results. The routed Marble path, a 41-point sweep, refresh and reanalysis were exercised in native KiCad Python.
- Extract Pins renders its three SVG diagrams natively, avoiding WebView2 preview failures, and exports interactive connector/pin HTML. Other workbenches include the UI, geometry, reporting and review changes described in their plugin guides.
- The IPC launcher, runtime setup and local installer were hardened for independent PCM packages and KiCad 10. Managed GUI launches now receive valid standard handles when KiCad supplies none. The local installer backs up existing copies.

## Validation and installation

Build the candidate with `python build_pcm.py --output-dir .validation/candidate-pcm-3.4.0`, then run `python tools/validate_packages.py --archive-dir .validation/candidate-pcm-3.4.0`. Preview local installation with `python tools/install_suite.py --version 10.0 --archive-dir .validation/candidate-pcm-3.4.0`; add `--apply` to install with backups. Restart KiCad and verify the 16 actions in PCB Editor. The [KiCad 10 audit](audits/2026-09-24-kicad10-local-validation.md) records the Marble project checks and their limits.

All engineering estimates remain subject to the affected plugin's documented geometry, material and solver limits. Constraint matches are not native DRC acceptance. Preview and source-hash checks do not replace project-specific review before applying PCB changes.
