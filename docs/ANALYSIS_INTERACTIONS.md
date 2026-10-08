# Analysis views and probes

These controls help inspect saved geometry and calculated results. Moving a view,
selecting a net or pinning a probe does not move PCB items or change a simulation.

## Choose a net in Quick PI or Quick SI

1. Save the board, including current zone fills.
2. Type part of a name into **Search nets**. Quick SI calls this **Search net names**.
3. Choose the matching net, or click **Select net on board** to open the saved-board
   picker. Click a pad, via or track to choose its net. Drag to pan and scroll to zoom.
4. Select the source and receiver/sink pads and run a fresh analysis. Choosing a
   different input clears the previous result; a selected net alone is not a result.

The picker reads the saved board. Save edits and reopen the tool to review a new
revision. It does not infer electrical sources, loads or driver parameters.

## Quick PI fields and 3D copper

In **Results**, hover over a solved triangle to read its cell value. Click to pin
that value. Holes, missing cells and disconnected copper do not acquire values by
interpolation. Disable the Matplotlib pan/zoom tool before clicking a probe;
**Ctrl-right-click** clears the probes. Changing the view or model clears them.

For the **3D copper** model, the native result dialog provides a top view and a 3D
view. In 3D, drag to orbit, use the Matplotlib pan controls to move the view, and
scroll to zoom. Click a displayed cell to pin its sampled value. Layer and field
selectors change the data shown. This viewport represents solved copper cells,
not STEP component solids or an assembly collision model.

**Export 3D report** writes an interactive HTML view and a paired JSON file.
Offline HTML controls are:

| Action | Control |
|---|---|
| Orbit a 3D plot | Drag |
| Pan a 3D plot | Shift-drag |
| Pan a 2D plot | Drag |
| Zoom | Mouse wheel |
| Restore the view | Fit |
| Read a value | Hover over a cell or sample |
| Pin a value | Click without dragging |
| Remove pins | Clear probes |

The 3D viewport displays at most 5,000 sampled connected cells for responsiveness.
The paired JSON retains the complete mesh and results. Probes report displayed
samples; they are not interpolated field queries. The planar report provides
interactive voltage-drop, current-density and loss-density cell maps alongside
static figures for printing. DC current-sweep reports also provide sampled probes.

## Quick SI routes, eye and step plots

The offline route report contains interactive cumulative delay, section impedance
and cumulative resistance plots, with static Matplotlib figures under **Static
export**. Hover near a sample and click to pin its value. Unknown values interrupt
curves; impedance markers distinguish extracted sections from ideal estimates.
A displayed sample does not resolve unmodeled via reflections or differential
coupling.

The illustrative eye and step plots offer the same offline sample controls. In the
native **Eye / step** panel, hover near a sample to read its time and voltage;
click to pin it and right-click to clear pins. Pins move with the plot when resized.
These are samples from the declared uniform-line model, not measured eye data or
protocol compliance results.

Native route previews have a coordinate cursor. Use **Probe** or **Ctrl-click** to
pin geometry coordinates, and **Clear probes** to remove them. A coordinate probe
is separate from an electrical result.

## Heater and planar magnetics previews

Hover to inspect coordinates. **Ctrl-click** pins a probe and **Ctrl-right-click**
clears pins. New patterns or analysis results clear stale probes.

- Heater thermal previews report the exact displayed grid cell temperature;
  pattern and organic-path previews report geometry coordinates only. Ordinary
  organic-path clicks and right-dragged heating regions retain their drawing actions.
- Magnetic winding previews report coordinates. Animated contours do not supply
  a local field solution and are not assigned fabricated field values.
- Motion plots report the exact time-series sample. Linear motion uses metres,
  metres/second, metres/second squared and newtons. Rotary motion uses radians,
  radians/second, radians/second squared and newton-metres.

For thermal board-specific controls, consult the
[QuickTherm guide](../quick_therm_plugin/QUICK_THERM_USER_GUIDE.md).
