# WayriCAD 3.6.42 publication

Published from `fc0202d6b110965bf9dbcc3fc5a2ec9606af83e4` after all eight
[exact-source CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40734325097)
passed across the configured Windows, Linux and macOS matrix and PI known-answer
benchmarks. Native reader and installed-IPC checks were performed separately
from the headless CI matrix.

## Included changes

Pin Extractor now contains connector-mating reviews, matching A/B label
proposals, CSV/TSV conversion, selectable numbering, bulk and individual label
copies and physical pinout grids. The native UI, CLI commands, offline guide,
README and package metadata are included. Earlier Quick-tool capabilities and
the existing screenshots were retained.

The functional feature source was tested with 43 native tests, including five
UI tests and native export of global/local/hierarchical label objects. The
release also fixes external-board reads in the installed IPC launcher through
a separate native worker, tested from an IPC-only parent. Another 28 related
source regressions passed before preparation;
22 package/version/CLI/documentation tests and 24 subtests passed during the
release build with candidate metadata in place.

## Package verification

The release has 24 independent PCM ZIPs, resources, wheel/source archives,
feed metadata, notes and SHA256SUMS.txt: 31 assets, about 74.47 MiB. Every uploaded
asset was downloaded and matched against its local SHA-256 before publication.
Public Pin Extractor, PI, SI, thermal and feed URLs were checked again afterward.
The PCM feed was promoted from those exact released metadata bytes.

Official schemas, payload syntax, icons, entrypoints, documentation images and
package hashes passed. The isolated wheel CLI/report smoke passed. Individually
extracted Pin Extractor, PI, SI and thermal ZIPs passed native KiCad Python CLI
checks without sibling source imports. New connector modules and guides were
confirmed in the wheel; the source archive contains their regression tests and
validation record. Private staging, boards, caches and environments were excluded.
The extracted Pin Extractor ZIP also loaded a real saved board through its native
reader from an IPC-only parent, preserving the input hash.

## Validation limits

See the [connector validation record](CONNECTOR_TOOLS_2026-10-28.md) for native
KiCad 10.0.6 / Python 3.11.5 / wxPython 4.2.2 checks, read-only Marble pin grids,
the source hash and the coordinate conventions. Contact correspondence is
planar; it does not certify manufacturer compatibility, keying or 3D fit.

Native label parsing/export passed. Interactive Eeschema paste remains
unverified because the desktop automation helper could not initialize. The
clipboard payload tests are not a claim that external-editor paste was completed.
Copied label anchors still need placement on the intended schematic pins/wires;
no existing PCB or schematic net is automatically renamed.

Existing release assets and tags were preserved. No local plugin installation
or production board modification was performed. Temporary extracted ZIP copies
created by this release task were removed after validation; current assets and
bounded verification evidence were retained.

The wheel matched 1,225 tracked source members; the source archive matched 1,600.
