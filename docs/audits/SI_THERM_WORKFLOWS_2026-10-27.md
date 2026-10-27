# Guided SI and thermal workflows — 27 October 2026

## Scope

Setup, input review, sampled-report interaction and export integrity. Existing
SI line/coupling and thermal equations are unchanged. Unknown physical inputs
remain unknown; numerical setup advice does not qualify a timestep or mesh.
No original/private board was modified and no local plugin was installed.

## Native captures

Windows, KiCad 10.0.6, Python 3.11.5 and wxPython 4.2.2. Opaque native client-area
captures were inspected for clipping, readability and private identifiers.
Rejected black sandbox captures were not promoted. No screenshot was synthesized.

| Capture | Saved source and assumptions |
|---|---|
| SI guided setup | Public Marble; SHA-256 `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`; `/ETH_PHY/MII_MDC`, U6.8→U54.16, reviewed GND return, explicit 50 Ω, effective Er 3.2, 1 ns rise, 100 MHz, 20 Ω driver and 50 Ω receiver. Setup only; unchanged PCB. |
| Thermal heating guide | Public thermal demo; SHA-256 `1cfc57ddd9bb546f22ad6984c961ce0745ec1c0f7b9203f749574ade49c9c3ee`; C1/C2/C3/J1 total 1.05 W, 20 °C ambient and explicit air cooling assumptions. Duration 10 s and 100 ms solver/frame intervals with declared copper/dielectric volumetric heat capacities. Setup only; unchanged PCB. |

Both plugin READMEs describe inputs and limitations next to the images.

## Verification

- Full portable thermal suite: 280 tests, 255 passed and 25 native capability skips.
- Final portable SI suite: 179 tests, 163 passed and 16 native capability skips.
  The final narrow reflow check also passed natively.
- Shared native transient/PI compatibility checks: 15 passed without skips.
- Shared report tests: exact extrema and limits, script-safe labels, event phases,
  row/trace selection, bounded probes, source fingerprints and paired-file rollback.
  JavaScript selection/hover logic ran in Node; browser rendering of the new
  local-file report was unavailable under the browser URL policy.
- Native guides were exercised with real wx controls, including modal power edits,
  stale-result invalidation and narrow-window scrolling. Final integrated and
  installer checks are recorded below when completed.

These checks do not establish live editor lifecycle on all platforms, whole-board
SI qualification, CFD or package gradients. Thermal material defaults are
illustrative. Imported PI losses remain fixed unless explicitly scheduled.

## Integrated package checks

The shared root suite completed 625 tests: 501 passed, 124 capability skips.
All 24 disposable PCM archives passed the official schemas, independent runtime,
entrypoint, icon and Python syntax checks. Extracted SI modules passed 16 tests,
including real guided/IBIS dialogs, without skips. Extracted thermal modules
passed seven helper/solver tests and a separate real modal heating guide at
560 px. Module paths and shared runtime came from each extracted installer;
source tests remained outside the installer.

Circuit export now uses `.tran TSTEP TSTOP 0 TMAX` with explicit reviewed maximum
step. The [ngspice manual](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
distinguishes output increment from the optional maximum integration step.
This does not establish waveform convergence or run an IBIS simulation.

The public PCM feed remains on the existing stable release. These changes are
source/candidate updates; no published assets were replaced.

The candidate wheel passed isolated CLI, report assets, Analytics Studio and
mechanical export smoke checks. New guided modules, report helpers and native
images match source bytes. The wheel excludes tests and bytecode. Both promoted
screenshots are opaque RGB with no embedded metadata. Final source documentation
and all 24 candidate archive checks passed. No local installation was performed.

Release preparation increments all packages carrying the updated shared runtime.
This preserves package-version immutability for the rebuilt archives. The source
commit used for publication must pass a fresh complete CI run after alignment.
