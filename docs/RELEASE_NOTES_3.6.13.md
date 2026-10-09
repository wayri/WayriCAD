# WayriCAD Mechanical Check 3.6.13 candidate

This source candidate improves Mechanical Check only. Other package versions and the public PCM feed remain at their published versions. Candidate binaries have not been promoted to the public repository.

- Native and offline inspection support two-part distance witnesses, point rulers, closest-approach hover lines, whole-board context, reference labels and top/bottom/side/isometric views with a millimetre scale.
- Exact native pair queries reuse transformed solids and reject changed analysis sources. Offline reports retain saved pair evidence and separate picked-point rulers.
- Nearest-part searches use bounds trees and cached measurements. Collision screening uses an adaptive broad phase and correctly includes diagonal cases that satisfy independent XY and Z limits.
- Viewports use indexed triangle picking and reusable GPU buffers. Quick 2D displays the saved Edge.Cuts contours, including cutouts, without inventing substrate solids or treating the outline as a collision candidate.

Exact 3D requires FreeCAD and usable models. Quick 2D remains conservative and incomplete for mechanical sign-off. See [validation evidence](audits/MECHANICAL_INSPECTION.md) and the [Mechanical Check guide](../mechanical_check_plugin/README.md).
