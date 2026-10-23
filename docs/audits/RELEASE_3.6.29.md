# WayriCAD 3.6.29 release validation

This release packages changes through `bf27b6b5`, plus release metadata and
documentation. Prior functional evidence is recorded in the
[Constraint Studio audit](CONSTRAINT_NATIVE_OVERLAP_2026-10-23.md),
[Fanout trials](FANOUT_REAL_BOARD_TRIALS_2026-10-23.md) and
[native screenshot audit](ROUTING_README_SCREENSHOTS_2026-10-23.md).

The candidate must pass exact-source CI, package/document checks, isolated wheel
imports and affected extracted-PCM workflows before publication. Public feed
descriptors remain on 3.6.28 until the new assets are published and their public
downloads match local SHA-256 hashes. No published asset is replaced.

All 18 IPC packages advance to 3.6.29. The six native packages receive independent
patch bumps to include the updated guides and screenshots without reusing old
package versions. Their functional source is unchanged apart from version
identifiers. The suite contains 24 independent PCM ZIPs.

Native source checks used Windows, KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2.
Full dense-board BGA/residual connector fanout remains unvalidated; the release
does not turn rejected or timed-out plans into successful routing. The Studio
fixture's native DRC reported violations, not a clean design.

## Published verification

- All eight required jobs passed for source commit `e309b35e` in
  [release CI](https://github.com/wayri/WayriCAD/actions/runs/39957613369).
  The release tag resolves to that exact commit.
- All 31 uploaded assets have matching server SHA-256 digests. Each public
  download was retrieved and matched the validated local bytes before feed
  promotion.
- All 24 PCM ZIPs passed official schemas, payload syntax, entrypoints, icons
  and feed hashes. Full documentation validation passed. Focused release
  contracts passed 26 tests and 24 subtests.
- The wheel passed isolated CLI, report/assets and local-server checks.
  Inspection covered 26 archives / 5,751 files without validation caches or
  known private paths; 1,230 tracked Python source-distribution members exactly
  matched the release source checkout. Complete source, plugin tests and
  development tools are available in the
  [tagged source archive](https://github.com/wayri/WayriCAD/archive/refs/tags/v3.6.29.zip).
- Final extracted Constraint Studio and Fanout PCM packages passed fresh
  KiCad 10.0.6 / Python 3.11.5 processes without sibling/source imports.
  Studio's removed editing operations rejected requests without mutation;
  protocol staging and review export preserved the public fixture. Fanout's
  null-netclass handling, duplicate-launch protection, fresh-pad planning and
  simple Adaptive stub continuation passed. Extracted WebView construction was
  checked; full extracted page loading and live editor attachment were not.
- All 90 native-package production Python modules match the prior source
  apart from the declared version identifiers. The six native patch releases
  refresh their bundled guides/screenshots without claiming new algorithms.

Public PCM descriptors are promoted separately after publication and download
verification. Earlier published versions and binaries remain unchanged.
