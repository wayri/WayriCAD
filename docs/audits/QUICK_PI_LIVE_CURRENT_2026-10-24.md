# Quick PI live-current validation — 24 October 2026

## Behaviour

The native Results workspace can adjust the total prescribed current by
Ctrl+wheel on solved 2.5D copper, or with the Total · A control. Plain wheel
scrolling zooms. Slow scrolling uses 0.1× the base step (up to five notches/s),
normal scrolling 1× (up to fifteen notches/s), and faster scrolling 5×. A pause
over 0.4 seconds or a reversal restarts finely. Fractional/batched wheel deltas
are respected. All sinks scale proportionally. Bursts coalesce, newer input
supersedes older calculations, and numerical updates run outside the window
thread. The board artists, zoom and selected PCB object identities remain in
place. Hover and pinned values, limits, summaries and export data are refreshed.
Export is disabled while an update is pending. Changed saved board bytes or
simulation inputs invalidate tuning. No board geometry is written.

This is a fixed-temperature linear update, not a new thermal or nonlinear solve.
It excludes resistive operating points, series/package paths, coupled returns,
3D and Joule-temperature feedback. Ordinary copper I²R loss remains included.

## Method and acceptance

For a fixed conductance matrix G, source-relative voltage u obeys G u = b.
Multiplying every prescribed sink current by k multiplies b, u and current
density J by k. Dissipation scales by k². Source voltage, conductivity, topology,
electrode membership and mesh remain fixed. Feasibility is checked again at the
new current. No matrix assembly, remeshing or factorization occurs per update.
The original refinement count is labelled as original-solve evidence.

Strict analytical strip, multi-sink and plated-via fixtures compare live results
with fresh solves, including limits and conservation. Tests also cover invalid
inputs, unsupported modes, independent returned results and JSON serialization.
Plot tests compare updated arrays, scales and via colours with fresh plots for
all metrics, cell/smooth rendering and fixed manual colour ranges.

## Public Marble results

The stored public Marble board snapshot has SHA-256
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
The existing meshes were reused; neither timing includes copper extraction or
remeshing. Fresh comparisons rerun the current FEM solver on the same mesh.
Each live median/max uses eight changes, from 0.6× to 1.4× the original load.
Times vary with hardware, runtime and concurrent activity.

| Case | Triangles / vertices / vias | One-time basis preparation | Live numerical median / max | Fresh solve range | Speedup against mean fresh solve |
|---|---:|---:|---:|---:|---:|
| 3V3 MMC multi-pin load | 79,135 / 71,031 / 990 | 1.091 s | 64.75 / 163.86 ms | 0.546–0.570 s | 8.62× |
| 3V3 USB multi-pin load | 27,595 / 25,576 / 528 | 0.483 s | 18.25 / 32.04 ms | 0.145–0.150 s | 8.09× |

Numerical timings: Windows, Python 3.14.2, NumPy 2.4.2, SciPy 1.17.0.
Native-window timing: KiCad 10.0.6 Python 3.11.5, wxPython 4.2.2,
wxWidgets 3.3.2, NumPy 2.4.2, SciPy 1.17.1, Matplotlib 3.10.8.
On the MMC case, eight changes from the live control to updated window state
measured **145.28 ms median, 156.31 ms maximum**, including the 16 ms input
coalescing delay. This is not a monitor scan-out measurement. Numeric vector
containers avoid repeated full-heap collection pauses; unchanged normalized
board/via colours reuse existing artwork. Manual scales, pinned labels and
other redraw requirements can take longer. This native window was exercised
against a saved public board, not a live editor IPC session.

Original boards were not modified. These measurements do not establish weak
hardware performance or accuracy of arbitrary unconverged meshes.

## Roundoff and mesh limitations

Fresh solves at 0.5× and 2× produced bit-identical J and power fields. At
nonbinary factors 0.1×, 1.1× and 1.5×, source-relative voltage differences were
at most 6.60 machine eps times the largest voltage offset. Sliver triangles
amplify that roundoff: the worst MMC triangle has area 1.35e-17 m² and a
shape-function gradient about 1.65e11 /m. Its local J component discrepancy
reached 9.96e-5 A/mm². Neither a new solve nor live scaling establishes precise
microscopic hotspot values on those triangles.

Across the tested factors, the energy-weighted J relative error was at most
1.71e-11 (MMC) and 5.05e-13 (USB). Peak vector-J relative error was at most
1.93e-8. Voltage-drop and total-power differences were at most 4.86e-17 V and
2.61e-17 W. Feasibility agreed and conservation checks passed.

Real-mesh acceptance retained strict voltage/power/scalar checks, peak-J
relative tolerance 2e-7, and energy-weighted J relative error ≤1e-9. The
per-component J check used its original 2e-9 A/mm² + 2e-7·|J| allowance plus
`16·eps·max|u|·sigma/1e6·sum_nodes|grad(N)|`, using each cell's actual gradient.
The underlying offset difference was separately checked below the 16-eps
allowance. This is a scoped double-precision comparison criterion, not a
universal solver error bound. Small well-conditioned fixtures retain strict
pointwise comparisons. Mesh refinement and physical validation remain separate.

## Automated checks

- Quick PI source suite: 351 passed, 56 skipped, 399 subtests passed. Native
  VTK meshing tests are separate from the source suite, as in repository CI.
- Shared repository suite: 596 passed, 123 skipped, 464 subtests passed.
- Native wx/pcbnew controls: 19 tests passed, including seven live-control tests
  and the inspector/canvas checks. Tests verify burst coalescing,
  latest-input publication, camera/artist retention, selection, normal zoom,
  toolbar gestures, context reads, stale-board invalidation, Ctrl-only current
  adjustment, speed-dependent steps, reversal reset and fractional wheel deltas.
- Shared probe interaction and performance checks: ten passed.

One captured-subprocess test initially failed before launching its worker
because Windows rejected pytest's inherited capture handle. It passed with
capture disabled; the full source suite above also ran with capture disabled.
Skipped dependency/native cases are not claimed as passes.
