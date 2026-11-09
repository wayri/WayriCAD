# WayriCAD 4.7.0

This minor release adds source-backed research antenna workflows to Quick
EMerge. The suite retains 27 independently installable packages. Quick EMerge
and the Python distribution advance to 4.7.0; other package versions are retained.

## Research antenna benchmarks

- Dual-feed polarized patch, dual-band WLAN monopole, printed CubeSat Yagi,
  ideal 4 x 4 AESA scan law, and circularly polarized CubeSat S/X shared aperture.
- Native geometry previews, compatible excitation presets, array-factor charts,
  CLI discovery/setup/phase inspection and bounded publication comparisons.
- Reports retain citation, source geometry, model limitations and geometry digest.
- Portable setup examples include step-by-step installation, GUI and headless
  execution, suggested sweeps, output interpretation and troubleshooting.
- The saved-copper inset-patch guide now documents extraction, port checks,
  threshold selection and controlled refinement separately from template runs.

See the [research walkthrough](../examples/quick_emerge/research_antennas/README.md)
and [validation evidence](../examples/quick_emerge/research_antennas/VALIDATION.md).

## Verification and limitations

The antenna feature passed the eight-job CI matrix on Windows, Ubuntu and macOS
with Python 3.10-3.14 coverage as configured. Twenty focused research tests passed
with EMerge/VTK; optional native-runtime skips remain explicit. The release
candidate is subject to the repository's packaging and independent-import gates.

Coarse WLAN and S/X screenings did not reproduce the paper matching/polarization
targets. They remain recorded failures, not qualification claims. The AESA model
is analytical array factor only; omitted feed networks, chassis, connectors and
deployment mechanics are not validated. Native GUI compatibility and numerical
convergence are distinct from automated CI success.
