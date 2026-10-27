# WayriCAD 3.6.40 publication

Published from `f7dd1831c26f825799409a64ee563cc4a1f329bd` after all eight
[exact-source CI jobs](https://github.com/wayri/WayriCAD/actions/runs/40564647638)
passed across the configured Windows, Linux and macOS matrix and PI reference
benchmarks. Existing tags and published assets were preserved.

The release contains 24 independent plugin ZIPs, resources, wheel/source archives,
feed metadata, notes and SHA256SUMS.txt. All 31 uploaded assets were downloaded and
matched against local SHA-256 hashes before publication. Public PI, SI, thermal
and feed download URLs were verified again after publication. The PCM feed uses
those exact released metadata bytes.

PI/SI/thermal code and assets match the native-tested candidates. Functional
source validation and platform limitations remain described in the individual
plugin guides and the following evidence:

- [Shunt capacitors](SHUNT_CAPACITORS_2026-10-27.md).
- [HTML/PDF and differential probes](REPORTS_AND_DIFFERENTIAL_PROBES_2026-10-27.md).
- [Copper view and identifiers](QUICK_PI_COPPER_LABELS_2026-10-27.md).
- [AC workflow and native captures](QUICK_PI_AC_READABILITY_2026-10-28.md).

The source archive includes the new guides and report tests. Private staging,
local boards, caches and virtual environments are excluded. No local plugin
installation or original PCB modification was made during publication.

The wheel contains 1193 tracked source members matching the tested checkout; the source archive contains 1544 matching tracked members.
