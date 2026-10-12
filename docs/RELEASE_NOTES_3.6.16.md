# WayriCAD 3.6.16

BOM Studio is now **Analytics Studio**, with saved-board copper and component
analytics alongside its existing BOM editing and export workflows. The package
identifier stays `com.github.wayri.wayricad.bom-studio`, so existing installations
upgrade normally.

- Measure copper unions and filled-zone areas by layer, net, net/layer and zone.
  Overlaps are counted once; supported drill openings are subtracted.
- Inspect board area/coverage, track lengths, via counts/spans and per-component
  pad-contact areas. Search tables and export CSV, XLSX, JSON or HTML evidence.
- Missing saved fills and unsupported geometry remain unknown. Save/refill in
  KiCad before analysis. Contact area is nominal pad land, not solder wetting or
  thermal conductance. Large board geometry may take time on its first analysis;
  repeated unchanged snapshots reuse a bounded cache.
- Constraint Studio starts with a full-width worksheet. Scope filters, board
  preview and rule details open on demand. Active filters remain clearable.
- A guided workflow, larger map, illustrated rule dimensions, expandable technical
  details and routing comparisons make constraints easier to read. Specialist
  tools remain available. Staging, undo, fingerprint checks, backups and offline
  apply behavior are retained.

All 17 IPC packages advance to 3.6.16. Fusion 0.9.8 and Variant Manager 0.6.1
retain their existing versions and published downloads. The suite still has
19 independently installable plugins. Refresh the WayriCAD repository in KiCad
PCM, install updates and restart PCB Editor.

See [Analytics Studio](../bom_studio_plugin/README.md),
[Constraint Studio](../protocol_constraint_composer_plugin/ReadMe.md),
[copper validation](audits/ANALYTICS_STUDIO_COPPER.md),
[UI validation](../protocol_constraint_composer_plugin/docs/UI_SIMPLIFICATION.md)
and [release checks](audits/RELEASE_3.6.16.md).

These are screening/review tools; geometry illustrations and condition matching
are not native DRC acceptance. Native compatibility across every OS, KiCad
version and DPI setting is not established by this release.
