# WayriCAD 3.5.0 release candidate

This candidate adds a direct **WayriCAD QuickTherm** action to the Quick PI PCM package. Its own icon opens the thermal tab in the native KiCad 10 window. QuickTherm reads saved footprint power and thermal-resistance fields, offers air and vacuum component screens, and can run optional thin-sheet or layer-resolved board models with explicit material and boundary inputs. It leaves the PCB unchanged and reports model coverage and limitations.

Quick PI also adds fixed-drop and current-dependent diode series elements, a native series-path editor, and return-path screening. These remain DC or steady-state screens; they do not provide coupled electrothermal simulation.

The suite still contains 16 independently installable PCM packages. Quick PI now exposes two PCB Editor actions: Quick PI and QuickTherm. Published 3.4.0 assets remain unchanged.

## Validation before publication

- Build the 3.5.0 source with `python build_pcm.py --output-dir .validation/candidate-pcm-3.5.0` and run `python tools/validate_packages.py --archive-dir .validation/candidate-pcm-3.5.0`.
- Run the affected Quick PI and QuickTherm tests, the repository CI matrix, and the native KiCad 10 launch and saved-board checks. Record skipped tests separately.
- Publish the source commit and versioned ZIP/wheel assets only after CI passes. Verify asset hashes, then promote `pcm/pkgs.json` and `pcm/repo.json`.

The [QuickTherm guide](../quick_pi_plugin/QUICK_THERM_USER_GUIDE.md) explains field mapping, virtual heatsinks, board models, result views, and unsupported physics.
