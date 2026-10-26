# WayriCAD 3.6.34

Quick PI now includes AC copper analysis for SMPS current spectra.

- Resolve skin and proximity effects in explicit straight copper sections and
  their return conductors. Sum DC and harmonic RMS Joule losses, with mesh and
  magnetic-boundary checks.
- Build triangular output-ripple or pulsed input-current spectra. Review the
  omitted harmonic content instead of assuming the spectrum is complete.
- Use the native AC window or `wayricad-pi --ac` to view current density,
  frequency-dependent impedance and harmonic losses. HTML/JSON reports include
  selectable tables, hover values and pinned probes.
- Existing DC I²R losses and the optional temperature-feedback checkbox remain
  available. AC loss uses a prescribed temperature; automatic board thermal
  coupling is a separate DC workflow.

The model accepts HV/LV and high-current operating inputs, but does not simulate
a complete switching converter, arbitrary board routing, vias, magnetic cores
or HV insulation. The reported AC voltage drop is across the modeled copper
loop, not the regulated output rail.

See the [AC methods and limitations](https://github.com/wayri/WayriCAD/blob/v3.6.34/quick_pi_plugin/AC_ANALYSIS.md),
[analytical/native validation](audits/QUICK_PI_AC_2026-10-27.md) and
[release checks](audits/RELEASE_3.6.34.md).
