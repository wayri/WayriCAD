# Installation and launch troubleshooting

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

## Installed package has no action, or clicking it fails

KiCad 10 IPC actions appear in the **PCB Editor** after their Python environment finishes preparing. Enable the API under **Preferences > Plugins**, inspect the editor's warning panel, and use **Recreate Plugin Environment** on a failed plugin after correcting its dependency/interpreter error. Repository discovery and plugin environment setup are separate steps.

Do not share API tokens when reporting errors. Include KiCad version, operating system, plugin name, and the error text with private project paths removed.

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
