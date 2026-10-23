# README catalogue and native screenshot recapture

The current default-branch README contains all 24 active plugin guides and a
gallery grouped by the same plugin names. Installation, first-use instructions
and the catalogue precede the full-size previews. The 10 October record below
describes the 19-plugin inventory at that time; the 23 October section records
the current documentation and new captures. Bundled tools remain under their
owning package, and earlier screenshots are retained.

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

## 23 October 2026 refresh

The root gallery now groups previews under all 24 plugin names. All 24 plugin
guides link to installation, first-use guidance, offline help and the CLI.
The refresh retains all 166 existing local image references across the root
README and those guides. Older captures remain historical examples.

Eight additional screenshots were captured from actual native windows on
Windows, KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2. They are opaque RGB
PNGs with empty image metadata. Headers, status bars and visible fields were
inspected for personal paths and identifiers. Source revision was `bb1caf53`.
These documentation changes do not replace published 3.6.28 binaries.

| New capture | What the capture establishes |
|---|---|
| [Quick PI / Marble](../../quick_pi_plugin/help-marble-geometry-3.6.28.png) | Saved `+12V` geometry loads; no PI solve was performed. Editable source/load defaults are not validated power-path roles. |
| [Thermal inputs](../../quick_therm_plugin/examples/quicktherm-input-3.6.28.png) | Four included parts with declared loads and limits; two mounting holes excluded. |
| [Thermal 3D](../../quick_therm_plugin/examples/quicktherm-3d-3.6.28.png) | Interactive surface and footprint markers; STEP loading disabled. |
| [Thermal paired views](../../quick_therm_plugin/examples/quicktherm-paired-3.6.28.png) | Top/back presentation of one approximate shared board-midplane field; this fixture has no bottom-side footprints. |
| [Connector before](../../fanout_generator_plugin/help-connector-before.png) / [proposed](../../fanout_generator_plugin/help-connector-proposed.png) | Six-pin disposable PTH fixture; six accepted escapes. |
| [Refiner validated](../../trace_refiner_plugin/help-validated-comparison.png) / [applied](../../trace_refiner_plugin/help-applied-refinement.png) | Five segments become one; native validation and Apply/Undo exercised on a disposable fixture. |

Thermal assumptions were 1.05 W total declared dissipation, 20 °C ambient,
35 W/(m·K) effective sheet conductivity, emissivity 0.8 and 10 m/s air. Automatic
meshing produced 600 cells. The approximate board field was about 23.6–27.3 °C;
declared junction-to-board resistances gave component junction estimates about
26.31–32.39 °C. The heat-balance residual was 2.62e-14 W. These are assumed-input
demonstrations, not physical qualification or resolved package gradients.
Both saved source boards were unchanged. Public Marble's SHA-256 remained
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.

The [routing capture audit](ROUTING_README_SCREENSHOTS_2026-10-23.md) records
the native fixture checks, UUID preservation and screenshot hashes. Existing
model limitations remain in each plugin guide.

| Additional capture | SHA-256 |
|---|---|
| `quick_pi_plugin/help-marble-geometry-3.6.28.png` | `83482d4e248054c2f33bc7781a7b431960e828105fedcf980f2e2b6f9ff7254e` |
| `quick_therm_plugin/examples/quicktherm-input-3.6.28.png` | `bcf7e1e9a08202066d95a447e58b3cc744fb859d85be84bd451230492f283929` |
| `quick_therm_plugin/examples/quicktherm-3d-3.6.28.png` | `20b798b227581b700edcfec6b041608f43ba3e249a6ee8246a5f3b4ddf6ba65d` |
| `quick_therm_plugin/examples/quicktherm-paired-3.6.28.png` | `5afeb9f5ad99789f80d0733f784f340c97dc2e754dded02e8819283bba853f6d` |

For this refresh, all 13 focused documentation regression tests passed, as did
the source documentation validator, existing-image retention check and PNG
metadata checks. The first-run native screenshots are evidence of the stated
source workflows, not installed-package or cross-platform acceptance.
