# WayriCAD 3.6.13 candidate

This source candidate improves Mechanical Check, Quick PI and QuickTherm and fixes the shared loading window. All 17 IPC packages advance to 3.6.13 because they carry the shared launcher. Fusion and Variant Manager versions and the public PCM feed remain at their published versions. Candidate binaries have not been promoted to the public repository.

- Native and offline inspection support two-part distance witnesses, point rulers, closest-approach hover lines, whole-board context, reference labels and top/bottom/side/isometric views with a millimetre scale.
- Exact native pair queries reuse transformed solids and reject changed analysis sources. Offline reports retain saved pair evidence and separate picked-point rulers.
- Mechanical Review now gives most of the window to the board, with a compact measurement/findings sidebar, explicit Load 3D models / 3D view actions, selected/hover labels, opaque PNG exports and rebuilt full-size help screenshots.
- Exact 3D adds CAD edge/edge, point/edge and geometric body-center rulers, alongside picked point/point and minimum surface gaps. Click a part for automatic CAD XYZ extents/ranges, volume and centroid. Manual edge numbers cover edges without display samples. Saved feature rulers remain distinct from clearance/nearest-part evidence and are preserved in offline reports.
- Global top/bottom height limits check every primary component solid on both PCB faces, including opposite-side protrusions. Violating parts show their excess height; an optional proximity warning threshold marks close component pairs without replacing collision or hard-clearance checks. Native and offline viewers keep these markers readable and preserve each finding's evidence.
- Nearest-part searches use bounds trees and cached measurements. Collision screening uses an adaptive broad phase and correctly includes diagonal cases that satisfy independent XY and Z limits.
- Viewports use indexed triangle picking and reusable GPU buffers. Quick 2D displays the saved Edge.Cuts contours, including cutouts, without inventing substrate solids or treating the outline as a collision candidate.
- Quick PI opens with a maximized board workspace, compact setup and inspection side panels, simple numeric inputs and icon actions. Panels can be hidden for a wider viewport; mesh settings, model details and the console start collapsed.
- Native planar views remove graph axes and plot margins, fit the saved board to the canvas, retain equal millimetre scale through resizing and show a compact ruler. Result colours and units move into the inspector. Scientific report exports retain their existing chart presentation.
- QuickTherm board views show only the selected component label and one temporary hover label. The main map, paired top/bottom workspace, 3D overview and interactive report no longer label every component in the thermal study.
- QuickTherm adds an editable scanned component table with always-enabled RθJB, Select all/none, filters, explicit overrides, limits and provenance. Its maximized workspace exposes axisless top/bottom/3D results, compact side controls and interactive orbit, pan, zoom, probes and details. Physical board studies can use power and optional RθJB without requiring RθJA.
- QuickTherm exposes transient board heating with a power-step table, Play/Pause, scrubbing and speed controls in native and offline 3D/planar views. A fixed study-wide scale and retained camera keep changes readable. Air/vacuum boundary controls are explicit. Schedule-event integration preserves short-pulse input energy; board-only manual studies export their input values and provenance correctly.
- The shared loading window hides immediately after a plugin signals readiness, before the launcher waits for the plugin to close. Queued wx destruction no longer leaves a blank loading window visible. Partially constructed loading windows are also cleared on startup failure.

Exact 3D requires FreeCAD and usable models. Quick 2D remains conservative and incomplete for mechanical sign-off. See [validation evidence](audits/MECHANICAL_INSPECTION.md) and the [Mechanical Check guide](../mechanical_check_plugin/README.md).

Quick PI retains its DC, transient and electrothermal model limits. See the [workspace validation](audits/QUICK_PI_WORKSPACE.md) and [Quick PI guide](../quick_pi_plugin/README.md).

QuickTherm retains its thermal models and unknown-value handling. See the [workspace validation](audits/QUICKTHERM_WORKSPACE.md), [label validation](audits/QUICKTHERM_LABELS.md), [transient playback validation](audits/QUICKTHERM_TRANSIENT_PLAYBACK.md) and [QuickTherm guide](../quick_therm_plugin/README.md).

See the [loading window validation](audits/LOADING_WINDOW_LIFETIME.md) and [runtime setup](../wayricad_runtime/RUNTIME_SETUP.md) for the shared launcher fix.
