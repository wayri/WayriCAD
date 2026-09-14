# WayriCAD BOM Studio 0.8 — measured performance

Executed on the recorded Linux/Python environment with **10,000 synthetic catalogue identities**, no CAD assets, three short provenance records per part. 12 iterations for each warm operation. Cold first query builds the derived index. The old and new finders were measured against the **same** temporary database in the same run; no production-device extrapolation is intended.

| Operation | Median / elapsed | P95 |
|---|---:|---:|
| Initial derived index + first 50 records | 845.159 ms | one cold measurement |
| New finder, unfiltered page of 50 | 29.614 ms | 32.619 ms |
| Previous finder, same page/data | 370.327 ms | 420.472 ms |
| New finder, exact indexed MPN | 24.415 ms | 35.395 ms |
| Numeric Temp_Max < 80 °C scan | 139.276 ms | 152.719 ms |

This is about 12.5× lower median backend time for the measured warm unfiltered browse, **not a whole-application speed claim**. Native parsing, large captured CAD meshes, browser paint, Windows/macOS and network/storage variability are not part of these numbers. Numeric predicates still scan applicable lightweight candidates. Full authoritative part records are loaded for the returned page only. Authoritative catalogue epoch remained unchanged.

The retained bounded-viewport regression exercised **50,000 synthetic browser rows** with a maximum 45 rendered data rows and recorded 906.3 ms for its initial-render measurement on this run. Those rows already reside in memory; grouped children are not fully virtualized. This is not a 50,000-component native KiCad parser benchmark or screen-reader certification.

Raw data: `validation-v8/finder-benchmark.json`. Reproduce (new output path):

```sh
python tests/benchmark_v8.py --count 10000 --iterations 12 --output new-benchmark.json
```

The benchmark creates and deletes its own temporary catalogue; it does not operate on your catalogue. Prior v0.6 benchmark JSON remains in historical validation folders.
