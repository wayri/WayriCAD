# Embedded 3D navigation

3D embeds show a small on-screen control group: Top, Bottom, Iso; left/right orbit, up/down tilt, counterclockwise/clockwise roll, and zoom out/in. Buttons have accessible names and shortcut tooltips. The group scrolls within short viewports and is absent in 2D/CAM views. Fit remains available in the main toolbar. These controls work with the classic script, custom element, ESM and lite viewer through the same Viewer API.

Click the 3D canvas or focus the viewer before using camera shortcuts. They are scoped to that viewer, including inside an iframe; other embeds and the host page are unaffected. Editable fields, selects, links, toolbar buttons, composition and Ctrl/Alt/Meta combinations are ignored.

| Keys | Action |
| --- | --- |
| 1 / 2 | Top / Bottom |
| 3 / 4 | Front / Back |
| 5 / 6 | Left / Right |
| 0 | Isometric |
| Shift + arrows | Orbit left/right or tilt up/down by15° |
| Shift + Q / E | Roll counterclockwise / clockwise by15° |
| + / − | Zoom in / out |
| F | Fit board |

Numpad0–6 and add/subtract are supported. Plain arrows, Space and P remain available to DemoController bindings. Any explicit active DemoController binding on the same chord takes priority over camera shortcuts, including bindings with preventDefault:false; one key never triggers both actions. A page does not receive global keyboard shortcuts from the library. Frame navigation keys differ from native KiCad shortcuts and are described by the button tooltips.

~~~js
viewer.setCamera3D('top');
viewer.rotate3D('left');                //15°, relative to the current screen axes
viewer.rotate3D('clockwise',30);        //roll; preserve target and camera distance
~~~

rotate3D accepts left, right, up, down, clockwise and counterclockwise, with a finite angle greater than0 and at most90°. It requires a loaded3D view; it does not edit saved design geometry, move components or clear source selection. Relative rotation uses the visible camera-up axis, including top-view poles and demo-framed geometry. View presets fit the board. Linked selection remains independent of camera navigation.

## Pointer navigation

Mouse/touch orbit now follows the visible camera frame and can pass continuously through top/bottom without a fixed-world-up pole flip or clamp. Rotation sensitivity is capped against a 600-pixel reference span, so small embeds do not amplify the same drag. Pointer navigation has no lingering damping momentum. Pan stays aligned to the screen after face framing or roll. Right-drag no longer triggers object/context picking on release; a stationary right-click retains the context menu. The Pan toolbar toggle enables left-drag panning and suppresses selection during that gesture. Toggle it off to orbit again. Measurement and demo controls remain separate.

To highlight without opening Properties, use new Viewer(element,{inspectOnSelect:false}), viewer.setInspectOnSelect(false), inspect-on-select="false" on the custom element, or inspectOnSelect=false in the iframe query. The inspector footer also has an Open properties on selection checkbox. Explicitly opening Inspect remains available; selection events, highlighting and properties data remain intact. The default is true for compatibility.
