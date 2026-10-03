# Installation and launch troubleshooting

[Illustrated user guide](USER_GUIDE.md) · [Runtime setup](../wayricad_runtime/RUNTIME_SETUP.md) · [Compatibility](COMPATIBILITY.md)

Start with the stage that failed. Adding a repository, installing a package,
preparing Python, opening the window and completing an analysis are separate steps.

| Symptom | First check |
|---|---|
| Repository added, no packages | Raw `repo.json` address, selected repository and search filter |
| Package installed, no action | PCB Editor, API enabled, environment preparation finished |
| Action reports JSON or environment error | Capture the actual error; recreate the environment only after correcting dependencies |
| Tool opens on an unexpected project | Launch from the saved project's PCB Editor; check multiple-instance notes below |
| Analysis is partial or empty | Selected scope, source/sink connectivity, filled zones and required stackup/models |

## Repository added but packages are missing

Add this exact repository descriptor in KiCad's Plugin and Content Manager (PCM):

```text
https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json
```

Select **WayriCAD Plugin Repository** in PCM's repository dropdown and clear the search field. `pkgs.json`, a plugin's `metadata.json`, and GitHub `/blob/` pages are not repository descriptors. Refresh the repository after updating its URL.

From a source checkout, run this read-only network diagnostic:

```sh
python tools/diagnose_pcm.py
```

It reports endpoint/JSON/hash failures and the number of compatible packages. Use `--platform windows`, `linux`, or `macos`, and `--kicad-version 10.0.5` to inspect compatibility rules. A successful check verifies repository discovery, not Python environment creation or every plugin feature.

Our v3.1.0 published feed returned 21 compatible packages during the September 2026 investigation. It omitted `schema_version: 2`; the corrected builder includes it and a package-feed digest. KiCad selects its validator using that integer, not `$schema`. The previous feed also passed v1 validation, so that omission alone did not explain every missing-package report.

## All IPC plugins fail while creating Python environments on Windows

If every WayriCAD action reports `.../bin/pythonw/.exe -m venv --system-site-packages ...` with Windows error 2, KiCad cannot start its configured Python interpreter. This occurs before WayriCAD code can run. Reinstalling PCM ZIPs does not correct KiCad's saved setting.

**Source installer:** close KiCad Manager and PCB Editor, then run `python tools/install_suite.py --apply` with the matching built release packages. Before copying any package, the installer detects the exact `pythonw/.exe` typo, checks the matching KiCad `bin/python.exe`, backs up `kicad_common.json` and repairs the interpreter setting. It refuses missing executables, other custom paths, or a running KiCad session rather than guessing. The repair is one-time; subsequent installations keep a valid setting unchanged.

**Already installed through PCM:** close KiCad and run `python tools/check_kicad_python.py --repair` from a WayriCAD source checkout. This makes the same narrow, backed-up repair without reinstalling all 16 packages. Restart KiCad afterward. Its first successful startup should create the missing environments. If a plugin retained a failed environment, right-click its action in PCB Editor plugin preferences and choose **Recreate Plugin Environment**.

If the helper cannot find a valid matching executable, open **KiCad Manager > Preferences > Plugins** and browse to the installed KiCad 10 `bin/python.exe` on that computer. Per-user installs often use `%LOCALAPPDATA%/Programs/KiCad/10.0/bin/python.exe`; machine-wide installs often use `%ProgramFiles%/KiCad/10.0/bin/python.exe`. If neither exists, repair KiCad itself. Do not copy another user's path.

KiCad stores the setting in `%APPDATA%/kicad/10.0/kicad_common.json` as `api.interpreter_path` unless `KICAD_CONFIG_HOME` overrides the root. PCM has no way to run a Python plugin before KiCad creates its environment, so a PCM ZIP cannot safely repair this host setting at install time. [KiCad's Plugins preferences](https://docs.kicad.org/10.0/en/kicad/kicad.html#plugins-preferences) and [IPC plugin environment guide](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/) describe those host controls.

## Installed package has no action, or clicking it fails

KiCad 10 IPC actions appear in the **PCB Editor** after their Python environment finishes preparing. Enable the API under **Preferences > Plugins**, inspect the editor's warning panel, and use **Recreate Plugin Environment** on a failed plugin after correcting its dependency/interpreter error. Repository discovery and plugin environment setup are separate steps.

Do not share API tokens when reporting errors. Include KiCad version, operating system, plugin name, and the error text with private project paths removed.

Current packages include local `help.html` and images. Start with the installed
tool's Help action or open that file directly. Standalone launches may request
a project; toolbar launches use their originating editor's context. Engines
that read saved files cannot include unsaved editor changes.

### BOM Studio stalls during startup on macOS

The 3.1.1 startup fix removes an unnecessary reverse-DNS lookup of the numeric
loopback address. The previous lookup could delay the readiness handshake past
its deadline even in headless mode. Update the package if an older launcher
log stops inside `socket.getfqdn` / `HTTPServer.server_bind`. This failure does
not require a longer timeout or a network connection for the local UI.

## Windows: two open editors and an unreachable second instance

We reproduced a KiCad **10.0.5 Windows** IPC endpoint collision with two disposable PCB editors sharing the same temporary directory. Both server logs advertised the same `api.sock` endpoint; the second editor could not be addressed independently. The corrected WayriCAD client uses the originating action's socket and token and refuses to fall back to another board, but cannot repair an already-bound KiCad server.

Open each project through this source-checkout helper to give each Windows editor its own temporary IPC namespace:

```sh
python tools/open_kicad.py "C:/projects/board/board.kicad_pcb"
```

Supply `--pcbnew "C:/Program Files/KiCad/10.0/bin/pcbnew.exe"` if needed. The helper preserves your normal KiCad configuration, library variables and project files. It waits for its editor to close and then removes its own temporary directory. Interrupting the helper leaves the editor running and retains its temporary files. It never modifies or stops existing editors. On Linux and macOS it launches the editor without the Windows temporary-directory workaround.

Two concurrent Windows editors with separate namespaces passed live socket/token project-identity checks and five fresh connections per editor. This is a tested workaround, not an upstream KiCad fix or proof that every KiCad version has the same behavior.

Maintainer reproduction commands (disposable projects and configuration):

```sh
python tools/validate_multi_instance.py
python tools/validate_multi_instance.py --separate-temp
```

The first reproduces the shared-namespace failure on the tested version; the second verifies the workaround. Only processes created by this harness are stopped. Detailed results remain under `.validation/multi-instance/` and should not be committed with API logs.

## Installation paths

The source installer honors redirected Windows Documents, macOS Documents and Linux `XDG_DATA_HOME`. `KICAD_DOCUMENTS_HOME` overrides the **base documents/data directory**; KiCad appends `KiCad/<version>/plugins`. `--destination` can explicitly select the complete plugin directory. Preview before applying:

```sh
python tools/install_suite.py
python tools/install_suite.py --apply
```

## Primary references

- [KiCad PCM repository format](https://dev-docs.kicad.org/en/addons/index.html)
- [KiCad IPC environment and plugin troubleshooting](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/)
- [KiCad 10 API server socket allocation](https://github.com/KiCad/kicad/blob/10.0/common/api/api_server.cpp)
- [KiCad 10 user-data path construction](https://github.com/KiCad/kicad/blob/10.0/common/paths.cpp)

See [native runtime setup](../wayricad_runtime/RUNTIME_SETUP.md) for corporate mirrors, proxies and offline wheels.
