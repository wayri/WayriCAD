# WayriCAD 3.4.0 release candidate

This candidate updates the 16 independent KiCad 10 PCM packages. The public PCM feed remains on 3.3.0 until the 3.4.0 source commit, CI, uploaded ZIPs and hashes have been verified. Do not replace published 3.3.0 assets with these builds.

## Changes

- BOM Studio displays a native loading window while it reads large saved projects, then a loading message until its embedded workspace is ready. Analytics now label measured observations and unknowns instead of presenting unsupported plots as insight.
- Constraint Studio retains the staged, reviewable project workflow and adds protocol-specific per-layer routing profiles with selected net groups, dimensional trace/pair previews and native KiCad sizing rules. Its embedded visual workspace completed the packaged WebView/native-message check on KiCad 10; startup errors immediately expose the native worksheet with an explanation.
- A live KiCad 10.0.6 route/via check confirmed 0.20 mm on F.Cu and 0.30 mm on B.Cu for an exact-net profile and a netclass profile when a new route starts on B.Cu with **Auto track width** off. With that option on, KiCad inherited the F.Cu width on B.Cu. KiCad also retains one width within an active route, so routing must end at the via and restart on the destination layer. Live differential-pair gap switching has not yet been checked.
- Trace RLC / Impedance Analyzer refreshes the board stackup without retaining stale analysis or AC-sweep results. The routed Marble path, a 41-point sweep, refresh and reanalysis were exercised in native KiCad Python.
- Extract Pins renders its three SVG diagrams natively, avoiding WebView2 preview failures, and exports interactive connector/pin HTML. Other workbenches include the UI, geometry, reporting and review changes described in their plugin guides.
- The IPC launcher, runtime setup and local installer were hardened for independent PCM packages and KiCad 10. Managed GUI launches now receive valid standard handles when KiCad supplies none. The local installer backs up existing copies.

## Validation and installation

Build the candidate with `python build_pcm.py --output-dir .validation/candidate-pcm-3.4.0`, then run `python tools/validate_packages.py --archive-dir .validation/candidate-pcm-3.4.0`. Preview local installation with `python tools/install_suite.py --version 10.0 --archive-dir .validation/candidate-pcm-3.4.0`; add `--apply` to install with backups. Restart KiCad and verify the 16 actions in PCB Editor. The [KiCad 10 audit](audits/2026-09-24-kicad10-local-validation.md) records the Marble project checks and their limits.

All engineering estimates remain subject to the affected plugin's documented geometry, material and solver limits. Constraint matches are not native DRC acceptance. Preview and source-hash checks do not replace project-specific review before applying PCB changes.
