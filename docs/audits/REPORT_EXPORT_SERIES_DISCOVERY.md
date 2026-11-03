# Restored report export and series discovery

On Windows with KiCad 10.0.6 and its prepared Python 3.11.5 runtime, the saved
VIN → MID → OUT series result reproduced failures in both HTML and PDF export.
The result retained `pocket_kivi_export` metadata, which the low-level portable
serializer deliberately refuses to wrap a second time. The report boundary now
validates and preserves that metadata while regenerating its source-custody
guard. Conflicting metadata and changed sources still reject publication.

The same saved full result exported to HTML and a 13-page PDF with eight raster
figures. Numerical values, original metadata and input file bytes were retained.
The shared helper is vendored independently into the affected plugin packages.

Quick PI now discovers bounded candidate net routes and proposed parallel banks
from the saved pad inventory. The native review dialog shows exact current and
excluded pins, allows part/pin selection and requires explicit missing models.
It returns the existing schema-1 series document, preserving normal parser,
draft and save/load contracts. The PI discovery CLI and RLC `infer-series`
command share the topology engine. RLC discovery does not extend its numerical
solver to multi-net circuits. Model boundaries for AC, transient and thermal
analyses remain as documented in the [path guide](../../quick_pi_plugin/SERIES_PAD_GROUPS.md#automatic-path-discovery).

Native saved-board acceptance discovered Q1 || Q2 followed by Q3 || Q4, entered
100/200 mΩ models and solved at 3.3 V, 2 A. All three nets and 20 current pins
survived simulation save/reload. Voltage drop was 0.27612677972172955 V, within
1 nV of the earlier manually configured reference. Both report formats exported
from that reloaded result. The source PCB hash was unchanged. The disposable
fixture has four known DRC findings and zero unconnected items; it is a workflow
fixture, not a manufacturing qualification.

Native wx checks exercised model entry, parallel/group retention and footer
visibility in a constrained 1200 × 700 display work area. Two existing native UI
tests also passed after correcting their fixture prerequisites and inspector
summary setup. Isolated installed-layout imports and reviewed route conversion
passed without source-checkout sibling imports. Public saved-board examples were
regenerated with all four native producers and verified with the existing viewer
adapters; source bytes remained unchanged.

Automated checks include 975 shared-suite passes (164 skips), 112 focused
report/discovery passes (five skips), and 601 Quick PI passes (91 skips), plus
four native wx test passes. These suites overlap; counts are not additive.
Skipped native coverage is not counted as a pass. Source documentation,
KiCad Python compilation and whitespace checks passed. Local checks do not
establish the complete cross-platform CI matrix.

Live desktop click validation of the new inference workflow remains pending:
Windows was locked when the test windows became available. Native automated
widget and saved-board checks do not establish a live-editor click-through.
No fresh native KiCad 11 qualification was performed; its support remains
experimental. Previously published 4.1.2 binaries have not been replaced.

## Compact reports in 4.1.3

Large interactive data is encoded with deterministic gzip, with no sample
removal, decimal rounding or network request. An offline Chromium check decoded
all three fields and the differential probe, rendered eight plots and exercised
Fit without script errors or external requests. Static PNG optimization preserves
dimensions, exact RGBA pixels, DPI, transparency and ICC profiles. Compact JSON
retains the same decoded numerical values. PDF page streams are compressed.

The same saved series fixture's HTML changed from 16,606,226 to 4,238,418 bytes;
PDF was 583,923 bytes, with 13 pages and eight figures. Its numerical sidecar was
6,224,137 bytes. All eight PNGs had identical decoded pixels before and after.
Rendered PDF pages and the browser field view were inspected for readable
headers, pin groups, tables and field shading. Large compressed plots require a
browser with the standard DecompressionStream API; static figures and exact JSON
remain available otherwise.
