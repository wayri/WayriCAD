# Reports and differential probes: source validation

Environment: Windows, portable Python 3.14.2 and KiCad 10.0.6 native Python
3.11.5/wxPython 4.2.2. Direct PDF checks used ReportLab 4.5.1, pypdf and Poppler.
This is development evidence for 3.6.40, not a published-release claim.

## Changes and boundaries

- Shared HTML has static section anchors, consistent typography/tables and print
  rules. Raw JSON stays in closed disclosures and is excluded from normal prints.
  Paired exports retain complete JSON separately.
- Direct PDF export is an optional, lazy dependency. It renders semantic text,
  tables and embedded PNG/JPEG without running scripts or fetching resources.
  Raw JSON is summarized with its text fingerprint unless explicitly requested.
  Canvas/SVG/external views are listed as retained in HTML. Wide tables repeat the
  identifier column; long tables repeat headers. Merged cells are simplified with
  a notice. Source/input aliases, stale hashes and failed publication are checked.
- The common JSON reader makes any tool's saved result available as HTML/PDF
  tables without recomputation. It is bounded; large sampled fields should use
  the originating tool's report exporter.
- Mechanical findings and project title are generated in HTML before scripts run.
  Analytics uses the common layout when the suite runtime is available, retaining
  its existing printable layout for standalone source use.
- SI pair comparison uses independently resolved propagation delays. Signed skew
  is N minus P; propagation phase is minus 360 times frequency times delay
  difference in seconds. Intended differential inversion is excluded. Lane
  matching compares the arithmetic mean of P/N delays, not receiver crossing time.
  Revision conflicts and duplicate routes are blocked; missing evidence stays
  unknown. Coupled/dispersive fields, device/package delay and compliance remain
  outside this calculation.
- PI A/B probes evaluate the solved P1 field inside a containing sheet triangle.
  Cached element weights resample current nodal values after load changes. They
  compare only one solved potential reference. Voids, unknown nodes, independent
  cases and full-volume/barrel-interior points are not inferred. Extra HTML probe
  maps stop above 20,000 triangles, retaining the saved table and native/CLI probes.

## Checks performed

| Check | Actual result |
|---|---|
| Shared root regressions | 649 run: 525 passed, 124 skipped |
| Focused PDF/export/custody/tool CLI + SI math | 38 passed |
| Final PI math/CLI and native A/B workflow | 11 passed |
| Additional native PI inspector/live regression group | 19 passed |
| Native SI suite | 198 run: 197 passed, 1 optional dependency skip |
| PI/Therm report regressions | 33 passed plus 13 subtests |
| Analytics tests, standalone and suite import contexts | 35 passed in each context |
| Mechanical core/report checks | 17 passed |
| Candidate packages | 24 ZIPs validated; 72 shared report modules byte-matched source |
| Wheel | Built, isolated smoke passed; new report/probe payload bytes matched source |
| Documentation and whitespace | Source documentation validation and diff check passed |

PDF tests check engineering units, every cell in a multi-page wide table, embedded
figures, hostile markup, omitted views, optional raw appendices, bounded inputs,
stale evidence and failed-publication preservation. The PI affine-field fixture
checks sign reversal, zero difference, unknown locations and overflow. SI checks
include 125 ps -> -45 degrees at 1 GHz and an inter-lane 1 ns -> -360 degrees.

Saved Marble PI, SI and thermal HTML exported successfully to PDF. All pages were
rendered with Poppler and reviewed for pagination and gross layout problems; these
were earlier illustrative studies, not new board simulations. A separate analytical
strip PDF retained its saved A/B potentials and difference. The synthetic SI timing
fixture's PDF decreased from 17 pages to five after suppressing raw JSON and
allocating table width to evidence. No private or original PCB was modified.

The new native PI screenshot is a genuine capture of the 10 x 1 mm, 35 micrometre
copper-strip fixture at 1 V/2 A; the file is RGB without metadata. Node checks ran
the HTML PI sampler. A full browser visual/interaction acceptance run was not
performed; PDF rendering and native-window tests are separate evidence.

Scratch remains under the existing validation directory: candidate ZIPs total
about 39 MB, plus the current wheel, PDFs, rendered QA pages and logs. Existing
shared scratch was preserved. Public 3.6.39 assets/feed were not replaced.
