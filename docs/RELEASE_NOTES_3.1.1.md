# WayriCAD 3.1.1

Installation, runtime isolation and project-context repair release. All 21 independent PCM packages remain marked testing; the limits below are material.

- PCM repository explicitly negotiates schema v2 and binds the package feed with SHA-256. A read-only diagnostic distinguishes a raw repository URL from a GitHub HTML page or package-list JSON and reports compatible entries.
- Desktop plugins use a private dependency environment based on KiCad 10 Python. Native workers run with isolated imports, preserve the originating IPC identity, and reject foreign Python/Conda settings. Setup supports configured mirrors, proxies and offline wheels without modifying KiCad's installation. Linux no longer attempts to build wxPython from PyPI during managed plugin setup.
- BOM Studio fixes a missing navigation JavaScript response and OS-dependent MIME types, supports the declared SDK patch range, isolates WebView profiles and recovers from a blank native view into the same local browser session. Five main views focus on reviewing, editing and exporting a BOM; advanced features remain available.
- Pin Extractor isolates its preview browser profile across plugin processes. Missing browser support now falls back to usable extraction tables/text previews and native HTML help instead of preventing the plugin from opening.
- The consolidated library/model tool is named **WayriCAD Embed3D** throughout the current UI, metadata and documentation. Its existing package ID is preserved.
- Saved-file launchers default to the originating PCB/project. Missing or unsaved context produces an actionable error instead of silently selecting another editor or the plugin directory. JSON errors identify the failing stage, and IPC tokens are redacted from launcher errors.
- Embed3D recognizes macOS system aliases such as `/var` while still rejecting project-owned symlink escapes.
- Installer destinations respect Windows redirected Documents, Linux XDG paths, macOS and KiCad's documents override.
- Quick PI includes native local Help and generates HTML inside its provisioned worker, so a clean standalone CLI does not need numerical libraries in its own interpreter.

## Validation and limits

Official schemas, all 21 ZIP payloads, icons, entrypoints and hashes were checked. An extracted Quick PI ZIP solved a Marble path and exported offline HTML from an unrelated working directory using a private runtime; the PCB hash remained unchanged. This is a regression fixture, not a board-wide power-rail loss claim. Native Quick PI: 49 tests; native Copper Balancer: 31 tests. BOM: 1,174 tests (2 skipped), plus real concurrent local server/view checks. Embed3D's portable suite: 319 tests (19 native-dependent skips). Mechanical: 24 tests; Visual Diff: 15 tests. Root and platform CI results accompany the release. A real IPC test of the packaged plugins opened two concurrent Pin Extractor windows: each extracted four rows and loaded SVG content in all three native previews. Packaged Fanout produced four escapes with zero rejections on the disposable fixture. Missing-browser fallback also retained four-row extraction and native help.

Two concurrent KiCad 10.0.5 Windows editors reproducibly collide on the same IPC endpoint when sharing a temporary directory. This is outside plugin control. `python tools/open_kicad.py path/to/board.kicad_pcb` provides a private temporary namespace per editor while preserving user settings. Both editors then passed correct-board checks and five reconnects each; wrong-instance tokens were rejected. The helper does not change already-running editors. See [troubleshooting](https://github.com/wayri/WayriCAD/blob/develop/docs/TROUBLESHOOTING.md).

Native BOM WebView concurrency passed, but a repeat required browser recovery for one window; unconditional embedded-view reliability is not claimed. Native Linux/macOS GUI operation, every plugin's live apply/undo flow, and KiCad 11 acceptance remain unverified. The current shared desktop runtime requires KiCad 10 Python; a KiCad 11-only installation is not supported by this release.

PCM repository URL: `https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json`. Select WayriCAD in PCM's repository dropdown. ZIP installation through PCM Install from File remains supported.
