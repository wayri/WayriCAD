# WayriCAD Visual Diff

Compare saved PCB and schematic Git revisions using KiCad's native SVG exporter. The compact local launcher creates one self-contained HTML report with side-by-side, overlay, swipe and raster change views. Choose sheets or copper layers, pan and zoom together, and fit the page or drawing. Report assets are bundled; no server, account or network connection is required.

Install its ZIP through KiCad 10's Plugin and Content Manager, then open **WayriCAD Visual Diff**. Choose a saved PCB or root schematic inside a Git repository, set Base and Head (defaults: `HEAD` and `WORKTREE`), and select **Create report**. Advanced rendering options hold PCB layers, a KiCad theme, the previous filename for renamed designs and an optional explicit KiCad CLI executable. A working-tree comparison includes saved, non-ignored untracked files; it does not include unsaved editor buffers. Add `.wayricad-visual-diff/` to your project's `.gitignore` to keep generated reports out of subsequent snapshots.

Git and KiCad 10+ CLI must be installed. On Windows the CLI is discovered from installed KiCad versions automatically. The desktop UI requires wxPython; optional IPC discovery uses `kicad-python` to preselect the saved board path, and file selection still works if IPC is unavailable. Comparisons never check out branches or modify project files. Failed report writes preserve an existing report. Large repositories are bounded at 250 MiB per snapshot; symlinks, submodules and Git LFS pointers are rejected with an explanation. KiCad 11 and live IPC acceptance remain unverified.

The suite wheel installs the `wayricad-diff` command. From the repository root:

```console
python -m visual_diff_plugin.kicad_vizdiff doctor
python -m visual_diff_plugin.kicad_vizdiff diff board.kicad_pcb --repo /path/to/project --base HEAD~1 --head WORKTREE --output review.html --open
python -m visual_diff_plugin.kicad_vizdiff view main.kicad_sch --repo /path/to/project --ref HEAD --output schematic.html
python -m unittest visual_diff_plugin.tests.test_visual_diff
```

Inside an extracted standalone plugin directory, use `python -m kicad_vizdiff` with the same arguments. Schematic hierarchy and project-relative libraries are copied into temporary snapshots for rendering. PCB comparisons retain common page coordinates; the raster change map is an aid to review, not an electrical-equivalence check or DRC.

The imported optional GitHub service remains separately invokable as `python -m visual_diff_plugin.kicad_vizdiff.server`. It defaults to loopback, fetches public repositories on explicit API requests, and needs the optional `cryptography` dependency for GitHub App authentication. It is never started by the plugin or local CLI. Configuring a GitHub webhook can publish check results and is an explicit external integration. No such integration is configured by this installation.

Imported at the user's request from `D:/PROJECTS-DEV/Kicad-plugins-dev/nativegitvizdiffkicad` (0.1.0). Original source hashes and the absence of an upstream license notice are recorded in `SOURCE_PROVENANCE.json`; no original author or upstream license grant is invented. The integrated suite bundle carries its GPL-3.0-only license.
