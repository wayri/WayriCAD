# Install WayriCAD in KiCad 10

WayriCAD is a suite of independent KiCad plugins. Install only the tools you
need through KiCad's **Plugin and Content Manager** (PCM). KiCad **10** is the
validated target. A KiCad 11-only installation is not supported by this
release; see [compatibility and known limits](COMPATIBILITY.md).

![Illustrated installation workflow](images/install-workflow.svg)

## Before you start

- Install and open KiCad 10.
- Use a normal KiCad project with a saved `.kicad_pro` and `.kicad_pcb` file.
- On the first launch, KiCad may need network access to create each plugin's
  private Python environment. It does not install packages into KiCad itself.
  Offline and corporate-network setup is covered in [runtime setup](../wayricad_runtime/RUNTIME_SETUP.md).

## Recommended: install from the WayriCAD PCM repository

1. In **KiCad Manager**, open **Plugin and Content Manager**.
2. On the **Repository** tab, choose **Manage…**, then add this complete URL:

   ```text
   https://raw.githubusercontent.com/wayri/WayriCAD/develop/pcm/repo.json
   ```

3. Return to the Repository tab and choose **WayriCAD Plugin Repository** from
   the repository list at the top. Clear the package filter if one is set.
4. Open the **Plugins** category, select the tool you want, and choose
   **Install**. Repeat for any other WayriCAD tools you need.
5. Open the **Pending** tab and choose **Apply Pending Changes**. An Install
   click only queues the operation; the package is not installed until pending
   changes are applied.
6. In KiCad Manager, open **Preferences → Plugins** and turn on **Enable KiCad
   API**. KiCad's Python interpreter must be an existing executable on this
   computer. The WayriCAD source installer repairs the known `pythonw/.exe`
   typo once with a backup; existing PCM installs can use its one-time
   [repair helper](TROUBLESHOOTING.md#all-ipc-plugins-fail-while-creating-python-environments-on-windows).
7. Restart the **PCB Editor**, open the project through KiCad Manager, and save
   its board. Launch WayriCAD from **Tools → External Plugins** or the **top
   toolbar**. The KiCad 10 packages include menu launchers alongside their IPC
   actions. Maximize the editor if the toolbar is crowded. Show or hide
   individual buttons under **Preferences → PCB Editor → Plugins**.

KiCad's [PCM manual](https://docs.kicad.org/10.0/en/kicad/kicad.html#plugin-and-content-manager)
describes repository management, pending changes, updates, and package
categories. Its [Plugins preferences](https://docs.kicad.org/10.0/en/kicad/kicad.html#plugins-preferences)
explain the API and Python interpreter controls.

## Install one downloaded package instead

This is useful when you want a specific release archive or do not want to add
the repository.

1. Download one `WayriCAD-<tool>-<version>-PCM.zip` from
   [WayriCAD Releases](https://github.com/wayri/WayriCAD/releases).
2. In **Plugin and Content Manager**, choose **Install from File…** and select
   that ZIP file. Do **not** unpack it first.
3. Apply any pending changes, enable **Enable KiCad API** under
   **Preferences → Plugins**, then restart the PCB Editor as in steps 6–7
   above.

Each PCM ZIP is a complete, independent package. Install a separate ZIP for
each tool you want.

### Install the 3.4.0 development candidate from a source checkout

The public PCM repository still serves 3.3.0 until the new ZIPs are published
and verified. To test the 3.4.0 candidate locally on KiCad 10, build and
validate independent packages, preview the destination, then install with
backups:

```console
python build_pcm.py --output-dir .validation/candidate-pcm-3.4.0
python tools/validate_packages.py --archive-dir .validation/candidate-pcm-3.4.0
python tools/install_suite.py --version 10.0 --archive-dir .validation/candidate-pcm-3.4.0
python tools/install_suite.py --version 10.0 --archive-dir .validation/candidate-pcm-3.4.0 --apply
```

Restart PCB Editor after installation. These local candidate ZIPs can also be
installed individually with PCM's **Install from File…** command. Do not upload
them under the already published 3.3.0 tag.

## First launch and project context

Launch WayriCAD from the PCB Editor for the saved project you want to work on.
The action receives that originating editor's board and project context; it
will not silently choose another open board. Save recent edits before launching
file-based workflows because those tools read the saved files.

Some WayriCAD commands prepare a private dependency environment the first time
they run. Wait for that preparation to finish. If it fails, correct the stated
Python, operating-system dependency, mirror, proxy, or wheel problem first,
then use **Recreate Plugin Environment** from KiCad's warning/error UI and run
the action again. See [troubleshooting](TROUBLESHOOTING.md#installed-package-has-no-action-or-clicking-it-fails).

## Updating without duplicate actions

Use PCM's **Installed** tab and its **Update** action, then apply the pending
change. Remove obsolete WayriCAD package entries if they still appear, so the
PCB Editor does not show duplicate commands. Current consolidations are:

- **Embed3D** replaces Localizer and Portable Assets.
- **Quick PI** includes PDN Decoupling.
- **Quick SI** includes Return-Path Auditor and Test Point Descriptor.
- Visual Diff and the standalone Design Variant Workbench are retired.

Removing a PCM package does not remove your project data. Keep project backups
and any existing BOM workspace files before changing installed tools.

## Platform notes

| Platform | What is supported now |
| --- | --- |
| Windows | KiCad 10 is the validated target. Two concurrently open PCB Editors can share an IPC endpoint on tested KiCad 10.0.5 Windows installations; [the documented helper](TROUBLESHOOTING.md#windows-two-open-editors-and-an-unreachable-second-instance) gives each editor a separate temporary namespace. |
| macOS | Packages declare macOS support, but native desktop operation has not been fully verified. A first launch can need the normal private Python-environment setup. |
| Linux | Packages declare Linux support, but native desktop operation has not been fully verified. Install the distribution's KiCad Python bindings, wxPython, and Python venv support first; WayriCAD does not build wxPython from PyPI. |

The packages are marked testing. No claim here establishes KiCad 11 support or
full live IPC acceptance for every tool.

## If the repository is empty

1. Confirm that the saved address ends exactly in `pcm/repo.json`. Do not use a
   GitHub `/blob/` page or `pkgs.json`.
2. In PCM, select **WayriCAD Plugin Repository** from the repository selector,
   clear the filter, and use **Refresh**.
3. Check the installed KiCad version. The feed is for KiCad 10; PCM normally
   hides incompatible versions unless **Show all versions** is enabled.
4. If KiCad reports a network, proxy, certificate, or package-feed error, use
   the address and error text to diagnose connectivity. For a source checkout,
   `python tools/diagnose_pcm.py` checks the feed without installing anything.

For a package that appears installed but has no command, complete the API and
first-launch steps above, then see [troubleshooting](TROUBLESHOOTING.md).

## Optional source and CLI installation

The source installer manages GUI packages directly. Installing the CLI alone
does not install or register GUI plugins.

- From a source checkout, run `python tools/install_suite.py` to preview the
  destination and `python tools/install_suite.py --apply` to copy the built
  PCM packages. It backs up replaced and retired direct installations. Build
  the packages first when the checkout does not already contain the matching
  release ZIPs.
- For terminal commands, download the release's `wayricad-3.3.0-py3-none-any.whl` and use Python 3.10 or newer. From the folder containing that file, run:

  ```console
  python -m pip install ./wayricad-3.3.0-py3-none-any.whl
  python -m quick_pi_plugin.cli --help
  ```

  The wheel provides commands such as `wayricad-pi` and `wayricad-si`. Module commands work when Python's scripts folder is not on `PATH`. Developers can instead run `python -m pip install -e .` from the source checkout. See the [CLI guide](CLI_USER_GUIDE.md).

KiCad documents [IPC plugin actions](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/#plugin-action-registration)
and their toolbar registration and environment setup.

## KiCad SPICE engine

Magnetic equivalent AC/DC and motor mechanical transient simulations use the ngspice shared library supplied with KiCad (or its distribution-provided simulation library on Linux). No separate simulator executable is needed. The simulation result records the engine version and library path. For a nonstandard KiCad installation, set `WAYRICAD_KICAD_NGSPICE` to the exact ngspice shared-library file used by that installation, then restart the plugin. An unavailable or incompatible library produces an actionable error; the plugin does not silently substitute another engine. Native execution has been verified on Windows KiCad 10; macOS/Linux discovery still needs native acceptance testing.
