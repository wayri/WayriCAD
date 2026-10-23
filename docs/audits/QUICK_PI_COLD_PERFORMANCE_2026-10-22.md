# Quick PI first-run performance — 22–23 October 2026

## Scope

This comparison uses the released v3.6.26 source at
`d3b1d70f9076516412c71001f04b428a6d6a9044` and the improved source on
Windows with KiCad 10.0.6 native Python 3.11.5, NumPy 2.4.2, SciPy 1.17.1
and VTK 9.6.1. Dependencies are already installed. Every measured request
starts a new Python process and a new native worker; no result cache or warm
worker is reused. Operating-system file caches are not flushed. Times vary
with host load; report the range as well as the median.

The public Marble PCB SHA256 is
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
The board remains unchanged. This is saved-file software verification with
assumed loads, not a measurement of the physical board or a mesh convergence
certificate. No private project is used.

## Complete first-run measurements

The primary measurement includes runtime discovery/dependency probes, a new
native worker, PCB loading, both geometry/mesh/FEM solves, full response
serialization and decoding in the caller. It excludes the extra diagnostic
copy written by the benchmark after the result returns. No result is reused.

| Trial | Released v3.6.26 | Improved source | Time reduction |
|---|---:|---:|---:|
| 1 | 53.967 s | 31.714 s | 41.2% |
| 2 | 43.239 s | 33.277 s | 23.0% |
| 3 | 41.907 s | 31.340 s | 25.2% |
| **Median** | **43.239 s** | **31.714 s** | **26.7%** |

The ratio of medians is 1.36×. Baseline range: 41.9–54.0 s; improved range:
31.3–33.3 s. The host was not dedicated to benchmarking; timing variation
limits extrapolation. Earlier diagnostic rounds are not substituted for this
final reviewed-code series. These are improvements to cold application jobs,
not a cold operating-system disk-cache test or dependency-download timing.

[Machine-readable trial record](QUICK_PI_COLD_PERFORMANCE_2026-10-22.json).
The six geometry/electrical evidence SHA256 values are identical:
`0c5e7e82ebddcab1807ec4beb42aca7629fedf26e56f33e82c372265c1a0cb75`.
This digest includes all potentials, currents and losses plus active-cell
centroids/thermal evidence, with the inactive-land exception explained below.

## Workload and electrical equivalence

Both rails run together in one batch, using VTK at an unchanged manual
2 mm edge and the existing contour subdivisions and contact partitions.
The original 400,000-cell limit per rail, 0.005 mm curve tolerance and
0.025 mm assumed barrel plating remain. Copper thickness comes from the
saved stackup. Fixed copper temperature is 20 °C with resistivity
1.724e-8 Ω·m; both loads have a 3.0 V minimum acceptance bound.

| Rail | Source | Ideal equipotential load | Current | Cells | Load voltage | Copper loss |
|---|---|---|---:|---:|---:|---:|
| +3.3P | SK1.199 at 3.3 V | U54 pads 6, 11, 19, 28, 50, 75, 100 | 0.2 A | 79,135 | 3.2684281761718124 V | 0.006314364765637482 W |
| +3V3_USB | L23.2 at 3.3 V | U23 pads 2, 16, 31, 36, 44, 50 | 0.15 A | 27,595 | 3.299734279264137 V | 0.00003985811037937659 W |

These are independent supply-net DC solves. No shared ground, thermal feedback
or AC interaction is inferred. Both rails contain actual filled copper,
tracks, pads and plated barrels across the board stackup. There is no synthetic
shortcut between the multi-pad load contacts.

Extracted geometry and conforming contours compare exactly. Every potential,
current density, sheet current, cell loss, via/contact/terminal result and
conservation field compares exactly. Active-cell centroids and thermal
budgets also compare exactly. Energy relative errors are approximately
4.12e-16 and 3.40e-16. An additional identical-mesh solver comparison finds
complete result dictionaries exactly equal, including analytics.

As in the earlier benchmark, VTK can choose different equal-quality
triangulations of zero-current copper lands. Complete mesh identity and
inactive-cell geometric/thermal identity are not claimed.

## Changes

- Import only VTK geometry/filter modules in the mesher and runtime probe.
  The native filter implementations and their settings are unchanged.
- Avoid an unnecessary native identity-probe process when all dependencies are
  already available; provisioning and locked managed-runtime checks remain.
- Own one loaded board within a multi-net batch. There is no global native
  board cache; another job loads its own board. Every case retains source-hash
  checks and batch invalidation when saved inputs change.
- Skip layer tests on unrelated ordinary tracks, while retaining every drilled
  pad/via void. Read each native contour point once through the native vector.
- Batch exact contour-neighbour queries with bounded allocations. Keep original
  corner coordinates, radii, candidate order and contact tolerances.
- Encode integer mesh-edge pairs for a faster lexicographic unique operation.
  Counts and inverse indices are unchanged; oversized indices use the original
  row-sort fallback to prevent integer overflow.
- Assemble sparse stamps using contiguous arrays in the same summation order.
  Reuse unchanged contact groups and convert full-field arrays to JSON in bulk.
- Avoid constructing layer defaults and hotspot dictionaries that are discarded.
  Stable top-12 ordering and all numerical summary values remain unchanged.

No copper contour, contact, hole, via span, curve tolerance, material value,
mesh target, sparse solve method, numerical tolerance or resource budget was
relaxed. Runtime startup and geometry/mesh construction still contribute
substantial first-run costs; this is not a suite-wide speedup claim.

## Verification

| Check | Result |
|---|---|
| Native Quick PI backend pytest selection | 323 passed, 332 subtests passed, no skips |
| Focused native mesher, geometry, batch ownership and runtime tests | 49 passed |
| Shared root suite | 503 passed, 227 subtests passed, 89 skipped |
| Source documentation and illustrations | Passed |
| Source compilation and diff whitespace | Passed |
| Independent source review | Memory-allocation concern fixed with chunk/count guards; no remaining findings |

Backend coverage includes analytical strips, multi-pad/multi-sink contacts,
floating copper, ideal shorts and series elements, holes and plated slots,
adaptive/manual mesh limits, 3D regressions, current/power conservation,
shared returns, return-path evidence, report generation, thermal feedback and
transients. Four native pytest warnings concern KiCad's deprecated SWIG
bindings; they are not silently counted as additional compatibility evidence.

Native pytest used separate local test tooling without installing into KiCad.
An initial unittest harness could not import two pytest-style modules; the
clean pytest run above collected those modules and completed successfully.
The root suite's skips remain skips; they are not included in passed counts.
This does not qualify live-editor interactions, every operating system, every
VTK release or an installed release archive. The changes are source development
work; existing v3.6.26 release assets are not replaced.

## Reproduction

`tools/benchmark_quick_pi_cold.py` accepts one saved solve/batch request and two
complete source/package roots containing matching Quick PI and runtime code.
It alternates baseline and candidate requests in fresh processes, saves complete
results, checks the PCB hash, and compares geometry and electrical fields after
every run. The reported main time ends when `run_job` returns its decoded
result; `process_seconds` also includes writing the diagnostic copy of that
result. Local output includes paths; review it before publishing.

```text
python tools/benchmark_quick_pi_cold.py request.json baseline-checkout candidate-checkout new-results-folder --python "C:/Program Files/KiCad/10.0/bin/python.exe" --trials 3
```

Mesh-only profiler runs and already-imported identical-mesh solver timings are
separate diagnostics, not substitutes for complete first-run measurements.
