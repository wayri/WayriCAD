# WayriCAD 4.8.1

This release aligns the 27 independently installable PCM packages and Python
distribution at 4.8.1. It expands Quick EMerge's passive phased-array FEM path
and adds a paired native radiation view. KiCad 10 remains the native baseline;
scientific packages retain their testing labels and documented model limits.

## Coupled FEM Phased Arrays

- **Setup > FEM phased array / AESA** loads a reviewable 2×2 passive inset-patch
  starting model. Arrays support 2–16 physical ports, at most 4 elements per axis.
- Fixed-phase scan-angle or explicit progressive-phase excitation, normalized
  uniform/binomial tapers, and explicit total incident power.
- Full coupled S matrices retain all 256 ordered entries at 16 ports. Delimited
  multi-digit names distinguish `S1_11` and `S11_1`, with legacy decoding and
  numeric Touchstone ordering preserved.
- Active-port reflection and incident/outgoing/net accepted-power diagnostics.
  S caps and reciprocity correction are disabled and recorded for array runs;
  apparent numerical passivity violations remain visible, not clamped.
- CLI: `python -m quick_emerge_plugin --write-fem-aesa-setup aesa.json
  --array-x 4 --array-y 4 --array-theta 30 --array-taper binomial`.

This uses EMerge FEM, not MoM. The generic passive patches are not the published
Verho active-array hardware. The ideal paper scan-law mode remains a separately
labelled fast reference. No active T/R network, measured gain, efficiency,
true-time-delay steering or full 4×4 convergence is claimed.

## Paired Radiation View

**3D + 2D radiation** displays an interactive 3D lobe and a selectable XZ/YZ/
azimuth polar cut together inside Quick EMerge. Both use the same stored angular
samples and global relative-field normalization. Original-sample probes are
linked; narrow windows stack the views. Array runs open the overview when
suitable samples exist. Changed inputs clear both panels.

The banner distinguishes coupled FEM from ideal array-factor data. Relative
field is not dBi. Reports, offline Help and the illustrated
[FEM AESA guide](../quick_emerge_plugin/FEM_AESA.md) explain units and limitations.
The root README also gains an authentic engineering-results collage and the
plugin README gains an image-led capability summary/open-to-run diagram.

## Verification

- Complete local Quick EMerge suite: **352 passed, 23 skipped**; 19 existing VTK
  deprecation warnings. Skipped environments are not compatibility passes.
- Stable EMerge 3.0.4 / emsutil 1.1.6: **two opt-in checks passed**. A small
  two-port array was solved with 8,094 tetrahedra at 4/5 GHz; coherent complex
  field-superposition relative error was approximately 1.2875e-15. The other
  check built/committed the actual 16-port geometry without a full array solve.
- Native paired-view, cut, original-sample, resize and stale-result checks
  passed in standalone Windows Python 3.11.9 / wxPython 4.3.1.
- KiCad-bundled Python UI import remains blocked on the audited installation
  by its missing `wx.svg._nanosvg`; that installation was not altered or counted
  as a pass. Earlier Windows help/WebView checks emitted a COM diagnostic while
  continuing; the final full local run completed.
- Final release assets must come from the exact source revision that passes
  hosted CI and be verified before PCM feed promotion. The published validation
  receipt records hosted jobs and artifact hashes separately from local checks.

The older 22-case adapter certificate binds its earlier source signature;
modified adapters require requalification for managed candidate activation.
The existing Constraint Studio Windows accessibility startup assertion remains
unresolved. This release does not claim all native crashes fixed or paper/
hardware/flight qualification. No local KiCad installation was performed on the
low-space system drive.
