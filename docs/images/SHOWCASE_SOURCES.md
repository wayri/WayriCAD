# README Showcase Sources

The banner assembles existing program captures and computed results. Images are
scaled proportionally, without cropping, recolouring, smoothing away numerical
detail or changing values. Headings and captions are added outside the images.
There are no generated substitute plots or fabricated application screenshots.

| Panel | Original image | Context and limitations |
|---|---|---|
| Power integrity | [Native Quick PI viewport](../../quick_pi_plugin/help-native-viewport.png) | Public Marble board, declared source/load example; the capture states mesh convergence is not verified. [Model guide](../../quick_pi_plugin/README.md). |
| 3D thermal analysis | [QuickTherm demonstration](../../quick_therm_plugin/examples/quicktherm-3d-3.6.38.png) | Assumed-load demonstration on a thermal example board; shared thin-sheet field, not CFD; STEP models disabled. [Guide](../../quick_therm_plugin/README.md). |
| AESA steering | [30-degree radiation view](../../examples/quick_emerge/research_antennas/images/aesa-vnext/30/3d-radiation.png) | Ideal array factor with isotropic elements; normalized relative field, not a full-wave array solution or measured gain. [Research examples](../../examples/quick_emerge/research_antennas/README.md). |
| Antenna fields | [WLAN 3D electric field](../../examples/quick_emerge/research_antennas/images/dense/wlan-field-3d.png) | Original solved samples at Z = 2 mm and 2.45 GHz. Visible sampling is retained; paper-derived reconstruction, not measured hardware. [Reproduction and qualification limits](../../examples/quick_emerge/research_antennas/README.md). |
| Magnetic fields | [Coupled-field window](../../planar_magnetics_plugin/help-coupled-field.png) | Independent coaxial transformer geometry, primary 1 A and secondary open; not inferred from PCB traces. Mesh/domain convergence is not certified. [Guide](../../planar_magnetics_plugin/ReadMe.md). |
| Signal integrity | [RLC eye/step comparison](../../signal_integrity_advisor_plugin/help-board-rlc-eye.png) | Two synthetic 60 mm PCB routes, explicit source/load assumptions; skin/dielectric losses and IBIS absent. Not measured or protocol-qualified. [Guide](../../signal_integrity_advisor_plugin/ReadMe.md). |

Regenerate from the repository root with Node.js and the existing `sharp`
dependency available: `node tools/generate_showcase_banner.cjs`.
The banner is a visual index; open the originals and guides for readable scales,
complete assumptions and the capabilities of the current plugin version.
