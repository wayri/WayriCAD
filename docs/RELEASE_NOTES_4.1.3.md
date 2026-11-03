# WayriCAD 4.1.3

HTML and PDF export now accepts restored simulations carrying valid portable
metadata. It preserves the original declarations and exact numerical evidence,
and still rejects stale sources or conflicting metadata.

Reports use lossless PNG optimization without downsampling, colour quantization
or gradient approximation. Large interactive plot payloads use offline gzip
compression; their samples and probe values remain exact. Modern browsers
decompress locally without network requests. Older browsers retain static
figures and the full numerical JSON. Standard JSON evidence is compact rather
than pretty printed, and PDF page streams are explicitly compressed. Images do
not replace the numerical data required for later inspection or simulation.

For the 15,104-triangle, three-net series fixture, HTML decreased from 16,606,226
to 4,238,418 bytes (74.5% smaller). PDF is 583,923 bytes and compact numerical
JSON is 6,224,137 bytes. All eight raster plots retain identical decoded pixels;
the 13-page PDF retains all eight figures. Sizes vary with geometry and samples.

Quick PI **Series → Infer paths from source to sink…** suggests net routes and
parallel component banks. Review every component's incoming, outgoing and
excluded pins; enter missing resistance, inductance or forward-drop values, then
use the reviewed path in the existing editor. The PI discovery CLI and RLC
`infer-series` command share this bounded topology engine. Discovery does not
establish copper continuity, device state or a converter model. RLC numerical
analysis continues to measure individual copper segments.

KiCad 10.0.6/Windows native saved-board checks retain all three fixture nets,
both parallel stages and 20 current pins through solve, save, reload and both
report exports. Native wx checks exercise model entry and small-screen controls.
The new workflow's live desktop click-through was unavailable because Windows
was locked. No new native KiCad 11 qualification is claimed; its support remains
experimental. See the [validation record](audits/REPORT_EXPORT_SERIES_DISCOVERY.md)
and [path discovery guide](../quick_pi_plugin/SERIES_PAD_GROUPS.md#automatic-path-discovery).
