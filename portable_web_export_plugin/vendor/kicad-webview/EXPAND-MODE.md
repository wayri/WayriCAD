# Expand mode and net shine-through

Expand mode is available in stable 0.8.0. The current source preview adds context fading for unselected vias while expanded; the published npm/CDN 0.8.0 package is unchanged.

```js
await viewer.load('/designs/project.json', {view:'3d'});
viewer.setRenderQuality('photoreal-fast');
viewer.setExpand(100); // accepted target, animated asynchronously
viewer.addEventListener('expandchange', event => console.log(event.detail.amount));
// viewer.setExpand(0) smoothly reassembles the board.
```

The compact **Expand mode** range accepts 0–100%. The first 35% lifts front components outwards and back components in the opposite direction, without separating copper. The remaining range separates copper, fades the existing substrate envelope to 2%, and stretches supported through-via barrels between their mounting planes. Separate physical core/prepreg/MCPCB solids are not reconstructed when they are absent from the renderer’s source geometry. Missing saved internal elevations remain explicitly illustrative.

The display is reversible: saved positions, units, identities and electrical connectivity are unchanged. Layers retain their normal palette colors while expanded; clearing a selection restores those colors. Hidden layers remain hidden. Components loaded later join the current pose. Copper and source selection remain linked across views; selecting a part focuses its current displayed geometry.

The transition can be reversed or retargeted without jumping to a fresh assembled pose. It honors reduced motion, pauses while hidden or off-screen, and stops scheduling frames at rest. During movement the framebuffer is capped at one million pixels; full resolution returns when motion settles. Shadows and ambient occlusion remain suppressed while expanded and resume after reassembly. This bounds work, rather than guaranteeing a frame rate on every device.

`setExpand` returns the accepted target; `getExpand()` returns the currently displayed progress. `setExplode`/`getExplode` remain compatibility aliases. Expand state, per-stage progress, offsets and measured geometry-update workload are available under `getRenderStats().expansion`.

Registered numerical fields/probes and physical-distance measurement are suspended while expanded because their registered physical elevations no longer match the display. Collapse to 0% to restore them. Native source/net cross-highlighting remains active.

## Highlighted nets shine through

Selecting a net draws a bright unlit overlay on its actual saved traces, pads and supported via barrels, including available internal copper. It remains visible through the substrate and component bodies, and follows layer separation and stretched vias. Copper fills stay faint, with bright real boundary edges, so a large ground plane does not conceal the whole design.

The overlay respects layer visibility and the existing accent/source highlight-color setting. It owns only its material, instance buffers and boundary lines; source geometry and materials are not replaced. Clearing selection removes it. It does not participate in picking, model fit, or electrical calculations. Limits are 50,000 selected instances, 2,048 source-mesh overlays and a bounded boundary-edge budget; a visible note identifies truncation. `getRenderStats().netGlow` reports the displayed count and limit state.

This is a visual inspection aid, not a simulation of emitted light, current or voltage. Source models, geometry and retained results keep their own provenance and limits.

Selected nets use native layer colors by default. In expanded Dim mode, only the selected net's via caps and stretched barrels retain gold; unrelated vias become gray with 24% fragment opacity, including when selected and unselected vias share one batch. Net changes update that emphasis without moving source geometry. Clearing selection restores the original materials and colors; collapsing restores the assembled-board via policy. Bright and Isolate remain explicit alternative highlight styles. Accent color remains an optional highlight setting. The inspector distinguishes the clicked object from its full-net highlight.
