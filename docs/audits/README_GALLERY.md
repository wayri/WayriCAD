# README catalogue and native screenshot recapture

The default-branch README now presents the complete active package catalogue
near the top, before the installation instructions and screenshot gallery.
All 19 rows link their package guides and match the active `metadata.json`
inventory. Feature descriptions include the recent BOM totals, PI transients,
electrothermal studies, thermal playback and mechanical measurement workflows.
Bundled tools are described within their owning package.

## Capture provenance — 10 October 2026

Several Windows native-window captures had undefined alpha-channel pixels. Most
of the PI and thermal-input screenshots therefore became transparent against
GitHub's dark theme. The source capture helpers now use 24-bit RGB targets for
these client-area images. These are new native captures, without retouching,
composited interfaces or changed numerical results.

| Capture | Public or generated input | Native check |
|---|---|---|
| [Quick PI workspace](../../quick_pi_plugin/help-workspace.png) | Generated `demo-power-board.kicad_pcb` context and a uniform 65 × 90 mm, 35 µm copper plate; 5 V source, 2 A load | Native workspace sizing, navigation and panel test passed. Analytical voltage drop remains 0.71149 mV. The pictured footprints/traces are context, not the solved plate geometry. |
| [QuickTherm component inputs](../../quick_therm_plugin/examples/quicktherm-input-workspace.png) | Saved public `thermal-demo.kicad_pcb`; C1, C2, C3 and J1 included, two mounting footprints excluded | Native service scanned the actual saved properties into the editable table. PCB hash unchanged. This capture does not run or qualify a thermal simulation. |
| [Mechanical Check workspace](../../mechanical_check_plugin/help-workflow.png) | Saved public `validation-fixture.kicad_pcb`; STEP geometry with deliberately low top/bottom height limits and a 20 mm proximity threshold | Seven solid bodies, two ray picks, four feature queries, five non-overlapping labels, two height violations and four proximity warnings; OpenGL error zero and PCB hash unchanged. Incomplete coverage remains visible. |

Captures used Windows, KiCad 10.0.6, bundled Python 3.11.5 and wxPython 4.2.2.
Their client-area sizes are respectively 1304 × 821, 1460 × 810 and 1184 × 781.
Only public/generated board filenames appear; no personal paths were included
and no redaction was required. Existing [PI](QUICK_PI_WORKSPACE.md),
[thermal input](QUICKTHERM_WORKSPACE.md#screenshot-provenance) and
[mechanical](MECHANICAL_INSPECTION.md) audits record the model scopes and earlier
acceptance checks.

The plugin-guide audit also found transparent
[QuickTherm 3D](../../quick_therm_plugin/examples/quicktherm-3d-workspace.png),
[paired thermal](../../quick_therm_plugin/examples/quicktherm-paired-workspace.png)
and [mechanical 2D](../../mechanical_check_plugin/help-quick2d.png) captures.
These were recaptured as RGB too. The two thermal views use the same four saved
power sources, 20 °C ambient, assumed 35 W/(m·K) thin-sheet conductivity,
0.8 emissivity, 10 m/s airflow and a 48-cell long-axis grid. The paired views show
one approximate board-midplane field, with the back view mirrored; internal
component gradients and STEP models are not part of that run. The mechanical
2D check verifies six footprint envelopes, two ray picks, three non-overlapping
labels, seven proximity warnings, zero OpenGL error and an unchanged PCB hash;
physical heights remain unchecked. These views are UI/model demonstrations.

The gallery uses one full-page-width image per preview and links every image to
its original pixels. Existing older previews retain their recorded generic-path
redactions. The 3.6.14 contact demonstrations retain their separate
[provenance](../assets/package-conduction/PROVENANCE.md).

## Reproduction and regression guards

Run the captures with KiCad's native Python, sequentially so the windows do not
obscure one another:

```powershell
$env:WAYRICAD_PI_WORKSPACE_CAPTURE = Join-Path $PWD 'quick_pi_plugin/help-workspace.png'
python -m unittest quick_pi_plugin.tests.test_workspace_ui -v
Remove-Item Env:WAYRICAD_PI_WORKSPACE_CAPTURE
python tools/capture_thermal_inputs.py --board-views
python tools/check_mechanical_workspace.py --mode exact3d --output-dir .native-temp/readme-mechanical
Copy-Item .native-temp/readme-mechanical/exact3d-workspace.png mechanical_check_plugin/help-workflow.png
python tools/check_mechanical_workspace.py --mode quick2d --output-dir .native-temp/readme-mechanical
Copy-Item .native-temp/readme-mechanical/quick2d-workspace.png mechanical_check_plugin/help-quick2d.png
```

The documentation validator rejects missing/duplicate catalogue rows, stale
inventory counts and transparent GUI gallery captures. It permits transparent
icons and SVG illustrations and does not apply the new opacity check to
historical release archives. This documentation correction does not replace
published binaries or change the package feed.

The 13 focused documentation regression tests and source documentation
validation passed. All 13 root-gallery captures are opaque, and the audit of
large PNG previews linked by plugin guides found no remaining transparency.
GitHub's Markdown API rendered the catalogue heading and all full-width image
links successfully. Native PI and both mechanical workspace checks passed;
thermal input and board-view captures preserved the saved source hash.
