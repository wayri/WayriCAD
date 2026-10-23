# WayriCAD 3.6.31

Quick PI now changes load current interactively on an analyzed 2.5D trace.

| Control | Behaviour |
|---|---|
| Plain scroll | Zoom normally. |
| Ctrl+scroll over solved copper | Adjust total load current. |
| Scroll slowly / normally / quickly | Use 0.1× / 1× / 5× the chosen Base step · A. A pause or reversal restarts finely. |
| Total · A | Enter the total directly or use its arrows. |

All sink loads scale proportionally. Voltage, current density, copper loss,
limits, probes, summaries and exported results update together. Zoom and
selected-object highlights remain. Wheel bursts combine into the latest input;
numerical work runs outside the window thread, and exports wait for completion.

On stored public Marble meshes, numerical updates measured 64.75 ms median for
79,135 cells and 18.25 ms for 27,595 cells, about 8.6× and 8.1× faster than fresh
solves on the same meshes. The larger native window case measured 145 ms median
and 156 ms worst over eight changes, including scheduling. Reusing board artwork
and avoiding temporary nested vector lists removes unnecessary recolouring and
collection pauses. These are measured cases, not universal latency guarantees.

Live tuning holds source voltage, temperature, conductivity, mesh and terminals
fixed. Resistive loads, series/package paths, coupled returns, 3D and
Joule-temperature feedback retain their normal Run workflows. It does not
establish mesh convergence or physical hotspot accuracy on sliver triangles.
See [method, timing and numerical checks](audits/QUICK_PI_LIVE_CURRENT_2026-10-24.md)
and [release validation](audits/RELEASE_3.6.31.md).

Refresh WayriCAD in KiCad Plugin and Content Manager, install the updates and
restart PCB Editor. All 24 packages include the updated shared runtime.
IPC packages use 3.6.31; native package patches are Trace Refiner 0.3.4,
Fusion 0.9.14, Variant Manager 0.6.7, Component Arranger 0.1.6,
Layer Counter 0.1.6 and Silkscreen Placer 0.3.6. Existing releases remain available.
