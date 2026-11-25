# WayriCAD 4.9.0

## Quick PI board viewport

- Switch among Full board, Analyzed nets, and Selected nets. Choose multiple saved
  nets and optionally dim surrounding copper without changing the simulation.
- Toggle copper, solved fields, and each side of the silkscreen independently.
  Use a manual color scale to compare views. Gray mesh cells indicate unavailable
  field values, and solved zeros remain on the numerical color scale.
- Hover over a physical copper layer to inspect board coordinates, net and layer,
  field values, grouped pads, and via barrel spans. Recall pinned probes after
  changing display scope or switching between board views.
- Show representative source-to-load track chains when saved endpoints and
  contiguous same-layer tracks establish a route. Via-barrel fields show solved
  current separately. Modeled series components have their own annotation.

Older multi-net result files may require a fresh solve before displaying fields
for a subset of nets. Use a physical layer for hover when projected layers
overlap. Quick EMerge retains its beta status.

See the [Quick PI guide](../quick_pi_plugin/README.md#board-viewport).
