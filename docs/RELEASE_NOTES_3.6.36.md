# WayriCAD 3.6.36

Layer Counter now mirrors the lower half of the full physical layer order by
default. On four layers, L1/L2 stay normal and L3/L4 are mirrored. Selecting
only some layers does not move the midpoint.

- Choose lower-half, legacy bottom-only, explicit core-face or no mirroring.
  Core-pair layout no longer silently overrides text orientation.
- Twelve added presets bring the total to 24: two-row, serpentine and radial
  layouts; triangle, pentagon, hexagon, chevron, capsule and double-ring cells;
  corner brackets, crosshair and ruler labels.
- The preview and saved native copper text use the same orientation. Zone-only
  keepouts still cover the complete measured counter, and grouped Undo/Redo is
  preserved.
- CLI adds `--mirror-mode`; existing no-mirror flags remain aliases. Help and
  guides include the corrected preview and new-style gallery.

The midpoint is defined by layer order, not dielectric thickness. Explicit core
pairs remain fabrication inputs; the presets are layout aids, not certified
registration coupons or manufacturing standards.

See [validation and preview provenance](audits/RELEASE_3.6.36.md).
