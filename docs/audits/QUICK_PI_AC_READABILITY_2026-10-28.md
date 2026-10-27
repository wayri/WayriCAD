# Quick PI AC readability and workflow

Development evidence for 3.6.40. Windows, KiCad 10.0.6 native Python 3.11.5/wx,
plus portable Python 3.14.2 for report and numerical tests.

## User flow

Quick loop shows the outgoing/return geometry before a solve. Basic operating
inputs precede the dimensions and ripple current. The main Run action applies
the visible quick recipe; a separate Apply action is no longer required. Custom
tables, waveform generation and solver settings start folded. Custom mode/imports
preserve their conductors and harmonics. Modified inputs clear old results and
export availability. Edited recipes clear the original input-file binding.

The setup stacks vertically in narrower windows. Results have four headline
quantities and one large selected chart rather than three crowded native plots.
Harmonic heating is the first view; the user can inspect physical copper/return
or resistance/reactance. Plot/table space is resizable. Row selection highlights
the relevant chart/conductor. Tables use kHz, mΩ and mW; source evidence retains
exact SI values. Frequency-chart coordinates remain Hz for picking compatibility.

Single-frequency data is discrete, not a fake logarithmic sweep. The current-density
colour scale represents the solved range; uniform fields have no artificial
gradient. Selected frequency charts skip building the unused spatial field.
HTML reports retain all three plots, readable checks and optional raw inputs.

## Numerical custody and captures

No change was made to the AC field solver. The existing explicit example remains:
20 mm length, 2 mm x 0.07 mm outgoing/return sections, centres separated by 0.8 mm
(0.73 mm surface gap), 20 C, 5 A DC plus 1 A RMS at 100 kHz, with 12 V context.
The actual native solve returned CONVERGED, total copper loss
0.1281255519668712 W and AC loss 0.004975551966871195 W. These match the original
example, now displayed as 128.1 mW and 4.976 mW. No PCB geometry or converter was
automatically inferred and no user board was modified.

The three new 3.6.40 screenshots are genuine native captures. Their RGB pixels
are unaltered and metadata-free. Setup, heating, impedance and short-canvas spatial
labels were visually reviewed. Initial captures exposed colourbar and conductor-label
overlap; positions were corrected and a wide/short-canvas bounding-box check added.
Earlier screenshot files remain available with their original provenance.

## Validation

- Native workflow checks cover recipe application, custom imports, source binding,
  stale-result invalidation, narrow layouts, row selection, actual field hover,
  cancellation and closing.
- Plot checks cover one/multiple frequencies, visible chart selection, units,
  short-canvas caption bounds, uniform/unknown fields and unchanged JSON values.
- Existing AC numerical/reference and worker/export custody checks remain active.
  Final focused run: 31 passed. The native workflow run passed eight tests.
- Shared root suite: 650 run, 526 passed and 124 environment-dependent skips.
- All 24 candidate ZIPs validated; the wheel passed isolated CLI/import smoke.
  Source documentation and whitespace checks passed. Source checks are distinct
  from installed native-host acceptance on other operating systems.

Candidate builds reuse existing output/cache directories. Public release assets
and PCM feed are unchanged until a maintainer release is published.
