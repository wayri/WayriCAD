# WayriCAD 3.6.38

Quick PI makes multi-pin endpoints and electrical studies easier to configure.

- Same-footprint, same-net source/sink pin recommendations appear only when
  eligible peers exist. Opt-in pin groups share one total current or power.
  Additional sinks support the same flow and mixed A/W loads.
- Constant-power 2.5D DC loads solve power at the actual terminal voltage, with
  high-voltage branch/collapse checks and final FEM energy conservation.
- Series paths detect two-pad components across the same net pair. Review and
  highlight parallel parts and confirm individual R/L models before inclusion.
- Source/sink markers are modestly larger and translucent. Ctrl+wheel works
  near markers and pad edges. Ambiguous nearby units leave currents unchanged;
  source targeting scales the total, sink targeting changes that unit only.
- Guided transient setup uses mΩ/nH/µF/µs, reviewed R/L/C inputs, safe single-path
  DC resistance reuse, timestep advice, JSON import/export and advanced SI mode.
- AC loop presets offer explicit dimensions/ripple and apply-and-run. Decoupling
  gains a separate lumped capacitor-bank impedance screen, target curves,
  resonance-aware sampling, probes and CSV export.
- CLI adds --load-power, repeatable --power-load and reviewed --series-file.
  Reports distinguish declared watts from solved amps and include nonlinear
  operating-point evidence.
- Fresh native screenshots and help cover PI, SI, Therm, RLC, Bulk Label Editor
  and Heater Designer; earlier large examples are retained. Scope/action-button
  layout, late-icon sizing and RLC unit text are corrected where validated.

Constant power is fixed-temperature 2.5D copper, including ideal pad units.
Series/package/3D, power-regulated transients/electrothermal, coupled-return power
and automatic fixed-current convergence are unsupported. Parallel series stages
currently use reviewed linear R/L models, not diode sharing. Transient/PDN L/C
and AC return geometry remain explicit: no unknown board parasitics or converter
control dynamics are invented. A sampled PDN target pass is not board proof.

[Validation and limitations](audits/RELEASE_3.6.38.md) ·
[Native capture provenance](audits/QUICK_TOOL_VISUALS_3.6.38.md).
