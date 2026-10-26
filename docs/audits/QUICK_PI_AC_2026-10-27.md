# Quick PI AC copper validation — 27 October 2026

## Delivered scope

Source after 3.6.33 adds an explicit, current-constrained 2D
magnetoquasistatic finite-volume conductor model. Straight rectangular copper
sections and their declared returns resolve skin and proximity effects. RMS
harmonics add copper Joule loss to mean-current loss. Zero-net-current passive
conductors can carry induced eddy currents. No PCB or converter geometry is
inferred from the optional saved-board provenance.

The native AC dialog, waveform helpers, CLI and offline HTML/JSON reports use
the same worker. The worker needs NumPy and SciPy; the explicit geometry path
does not load VTK or native board IO. Cancellation terminates the worker.
Source hashes, protected output paths and paired-report rollback are checked.

DC Joule loss already existed. The saved-board **Include Joule heating /
temperature feedback** checkbox still controls a separate DC electrothermal
iteration. AC losses use prescribed temperature and are not silently mapped
into that board thermal model.

## Numerical evidence

Windows, KiCad 10.0.6, bundled Python 3.11.5 and wxPython 4.2.2 were used for
native checks. The portable run used Python 3.14.2. BLAS worker counts were
limited to one during numerical tests.

- Independent low-frequency resistance and RMS I²R checks pass, including
  direct integration of exported loss density and conductor-power sums.
- For opposed 6 mm wide, 0.07 mm thick plates with a 0.02 mm gap, the
  one-sided infinite-width slab reference is
  `Z = [2 rho k coth(k t) + j omega mu gap] length / width`,
  `k = sqrt(j omega mu / rho)`. At 100 kHz and 1 MHz, resistance differs by
  less than 0.9% and reactance by less than 3.1%. Finite-width fringing and
  discretization remain; this is an asymptotic reference, not exact geometry.
- Tests cover high-current quadratic loss scaling, HV/LV voltage-context
  invariance, passive shield eddy loss, Fourier Parseval accounting, missing
  returns, touching conductors, stale inputs, overflow, electrical size,
  budget failures and honest UNCONVERGED results.
- The synthetic example has 10 A DC plus 1 A RMS at 100 kHz and 0.3 A RMS at
  300 kHz, 20 mm length, 1 × 0.07 mm outgoing/return copper and 60 °C.
  DC loss is 1.14007344 W and AC loss is approximately 0.01248958 W.
  The air padding increases from 0.5 to 1 to 2 mm. Final global mesh and
  boundary differences are approximately 0.286% and 4.310%, within the
  explicitly selected 5% tolerance. Current and real-power residuals are
  below 1e-12. This is synthetic input, not a measured SMPS validation.

Convergence qualifies global loop impedance only; it does not qualify the
local peak-current map. Path length and transverse size must remain below
the electrical-size guard at each supplied frequency. Return-current splits
are prescribed assumptions. Truncated waveform spectra retain omitted-RMS
information; omitted loss is not presumed negligible.

## Workflow and package checks

- Full local PI collection: 396 passed, 65 skipped and 422 subtests passed;
  11 VTK-dependent checks failed because VTK was absent in that Python.
  All 16 mesh checks subsequently passed in the prepared native runtime.
- Final combined native run: 39 tests passed in 45.948 seconds, normal exit.
  This includes the 14 AC numerical/input tests, nine workflow tests and
  16 mesh tests. Native UI checks cover actual fields, hover, table selection,
  invalidation, cancellation and normal teardown.
- The actual `wayricad-pi --ac` path prepared its managed worker and exported
  the bundled example as paired HTML/JSON with CONVERGED status.
- All 24 disposable PCM ZIPs pass schemas, independent runtime/action checks,
  icons and syntax validation. An extracted PI installer ran the actual AC
  worker and report; new production modules match archive bytes. Published
  release files and feed were not overwritten.
- Edge verified all three report visuals, conductor/table selection, harmonic
  probes, sorting with retained identity and clear selection; no JavaScript
  errors. Source documentation validation passes.

`help-ac-study.png` is a native client capture of the computed synthetic loop
under a normal application event loop. The current-density colour scale starts
at zero. Numerical values and pixels were not edited; no private design or
local path is visible. Superseded capture attempts were not used.

## Interpretation limits

The AC workflow does not simulate nonlinear SMPS switches, control loops,
magnetic cores, capacitor filtering, dielectric loss, radiation, arbitrary
board routes, vias or changing cross-sections. Its series copper-loop AC drop
is not regulated output-rail ripple. High voltage is operating context, not
an insulation or creepage qualification. Fixed-temperature high-current losses
do not establish cooling, operating temperature or ampacity.

See [methods and primary references](../../quick_pi_plugin/AC_ANALYSIS.md).
