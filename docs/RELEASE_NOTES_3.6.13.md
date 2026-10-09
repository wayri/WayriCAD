# WayriCAD Mechanical Check, Quick PI and QuickTherm 3.6.13 candidate

This source candidate improves Mechanical Check, Quick PI and QuickTherm. Other package versions and the public PCM feed remain at their published versions. Candidate binaries have not been promoted to the public repository.

- Native and offline inspection support two-part distance witnesses, point rulers, closest-approach hover lines, whole-board context, reference labels and top/bottom/side/isometric views with a millimetre scale.
- Exact native pair queries reuse transformed solids and reject changed analysis sources. Offline reports retain saved pair evidence and separate picked-point rulers.
- Nearest-part searches use bounds trees and cached measurements. Collision screening uses an adaptive broad phase and correctly includes diagonal cases that satisfy independent XY and Z limits.
- Viewports use indexed triangle picking and reusable GPU buffers. Quick 2D displays the saved Edge.Cuts contours, including cutouts, without inventing substrate solids or treating the outline as a collision candidate.
- Quick PI opens with a maximized board workspace, compact setup and inspection side panels, simple numeric inputs and icon actions. Panels can be hidden for a wider viewport; mesh settings, model details and the console start collapsed.
- Native planar views remove graph axes and plot margins, fit the saved board to the canvas, retain equal millimetre scale through resizing and show a compact ruler. Result colours and units move into the inspector. Scientific report exports retain their existing chart presentation.
- QuickTherm board views show only the selected component label and one temporary hover label. The main map, paired top/bottom workspace, 3D overview and interactive report no longer label every component in the thermal study.

Exact 3D requires FreeCAD and usable models. Quick 2D remains conservative and incomplete for mechanical sign-off. See [validation evidence](audits/MECHANICAL_INSPECTION.md) and the [Mechanical Check guide](../mechanical_check_plugin/README.md).

Quick PI retains its DC, transient and electrothermal model limits. See the [workspace validation](audits/QUICK_PI_WORKSPACE.md) and [Quick PI guide](../quick_pi_plugin/README.md).

QuickTherm retains its thermal models and unknown-value handling. See the [label validation](audits/QUICKTHERM_LABELS.md) and [QuickTherm guide](../quick_therm_plugin/README.md).
