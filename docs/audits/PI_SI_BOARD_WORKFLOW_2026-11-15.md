# Local PI/SI Board Workflow And AC Ports Validation

Date: 2026-11-15. Base: published 4.8.4 / develop feed commit `3fdb49f`.
These are local source changes, not an installed or published release.

## Scope

- Root README: installation/tool choice first, release history near the end;
  existing collage remains immediately below badges.
- PI and SI: origin-bound asynchronous selection following while idle,
  explicit pad-role commands and reverse PCB selection. Closed/disabled/stale
  callbacks are discarded. Missing or ambiguous UUIDs do not choose a net.
- PI series diagram: numbered source/rail/device/load stages, parallel lanes,
  distinct colours, arrows, zoom/pan and the same SVG drawing commands.
- Two-port MQS: explicit rectangular sections/returns; one factorization for
  both excitations per frequency and mesh. Numerical refinement remains distinct
  from physical qualification.
- Planar PDN: a separate triangular parallel-plate cavity model with distributed
  capacitance, ideal reference and magnetic walls. Saved-copper adaptation rejects
  multilayer/nonplanar/nonuniform sheets, vias/barrels including omitted DC stubs,
  stale configuration and mismatching geometry fingerprints.
- Plots: all four log-log magnitudes, actual-reference overlays, signed dB
  differences at common samples only, original-sample probes, sortable numerical
  table, pan/zoom and source-protected JSON export.

## Checks Performed

Windows, KiCad 10.0.6 bundled Python 3.11.5, and an existing Python 3.11
scientific runtime. No dependency install or solver build was performed.

| Check | Result |
|---|---|
| Broad Quick PI tests, excluding the optional production-mesher file | 710 passed, 79 skipped |
| Broad Quick SI tests | 221 passed, 39 skipped |
| Final focused solver, adapter, CLI, comparison and selection tests | 46 passed |
| Native PI/SI workspace and AC window regression set | 14 passed |
| Latest AC native UI checks after sorting/stale-table changes | 3 passed |
| Documentation source links/images and whitespace | Passed |

Counts overlap and must not be summed. Skipped checks are not passes. An initial
broad suite result describes its integration checkpoint; final adapter/table
refinements were rechecked in the focused/native sets rather than claiming a
second complete CI run on a frozen release commit. An initial
broad run used an interpreter lacking scientific packages in isolated subprocesses;
the scientific-worker check passed after using the existing complete runtime.
Initial SI report failures likewise reflected missing matplotlib in that
interpreter; the complete scientific-runtime suite passed. No baselines were
weakened to hide failures.

Native tests mock only standalone ActionPlugin registration because no live
KiCad application manager exists in that process. They exercise real wx windows
and controls, not live IPC operation against a PCB Editor. An actual native AC
result window was inspected; later magnitude/comparison layouts also passed the
native tests. No screenshot of another application is treated as UI evidence.

Independent source review identified configuration snapshot drift, a 3D-mode
guard using the wrong request field, and omitted plated stubs. All three were
fixed, with focused regression checks. No independent measured/Palace accuracy
or performance comparison was performed.

## Numerical Evidence

The rectangular cavity test compares its first longitudinal resonance with
`c / (2 L sqrt(epsr))` using an explicit mesh and sampled sweep, with a 2%
acceptance tolerance. Other tests cover low-frequency capacitance, units,
orientation/port permutations, reciprocity, current balance, power and passivity.

[Reproducible plotted example](../../quick_pi_plugin/examples/planar_pdn/README.md)
contains actual fine/coarse results and original inputs. The image is a computed
plot, not a native screenshot, measurement or Palace result. Noticeable errors
near higher resonances remain visible. Neither mesh is automatically qualified.

## Remaining Limits

Selection maps to a saved snapshot; unsaved editor geometry/net edits are not
analysed. Live cross-selection needs an originating-editor acceptance run.
MQS excludes displacement capacitance; planar PDN includes local capacitance but
omits fringing, radiation, real return-plane losses/voids, vias, launches, discrete
components, dielectric dispersion and multilayer coupling. Narrow traces may not
meet parallel-plate assumptions. `MODELLED` does not mean converged. Cancellation
is cooperative between sparse solves. No Palace fork, benchmark speedup, native
installation, release build or publication is claimed.

All generated test scratch and retained logs are on D:. The reproducible example
is about 1.23 MB plus its plot. C: remains critically below the required reserve
(about 5.2 GiB free); no storage-intensive task was run there.
