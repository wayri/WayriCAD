# 3.6.38 validation: Quick PI endpoints, loads and guided studies

## Implemented model and UI contracts

Pin recommendations use the exact footprint UUID and net, not reference text.
Pads assigned to another source/sink unit are excluded. The checked group is one
ideal equipotential electrode; declared A/W is the total and contact currents
follow copper conductance. New requests invalidate previews and results.

Constant-power ports use fixed-mesh FEM response reduction followed by a small
damped Newton solve on the positive incremental high-voltage DC branch. The
final FEM checks delivered P=VI, source/load/loss energy balance and budgets.
This is not converter dynamic stability or source foldback. Reduction performs
power-port count + 2 FEM solves, without remeshing. See
[constant-power equations and limits](../../quick_pi_plugin/CONSTANT_POWER.md).

Detected parallel components must span the same oriented saved net pair. Each
reviewed R/L element retains its own pad geometry and conductance; neither
resistances nor currents are blindly split equally. Native parallel-resistor
checks account for copper spreading/lead losses separately from ideal branch
resistance and preserve the saved input hash.

Marker hit testing uses projected pad outlines and marker centres with a
screen-sized proximity radius. One grouped unit is one target. Ambiguous units
consume Ctrl+wheel without changing total or individual demands. Plain scrolling
still zooms, stale-board guards remain, and current-only live updates retain
artists and zoom. Constant-power rescaling is explicitly disabled.

Transient setup retains the existing passive source/path R/L + effective C/ESR
backward-Euler model, with independent timestep refinement/error checks. One
matching feasible DC path can seed total R. Missing L/C is not inferred. The
new editor uses engineering units and retains the advanced SI representation.

The AC quick setup supplies explicit balanced loop models, not automatic PCB
extraction. PDN capacitor-bank impedance uses declared source R/L and capacitor
C/ESR/ESL. Independent complex-network, capacitive limit, SRF/quantity and high-Q
antiresonance references were checked. Coarse/refined sampling includes analytical
resonance candidates; a sampled target status is not full board qualification.

## Completed development evidence

Windows, KiCad 10.0.6, Python 3.11.5, wxPython 4.2.2:

- Integrated native endpoint, mixed-load, parallel-path, marker/scroll and
  guided AC/transient/PDN tests: 53 passed, no skips.
- Constant-power analytical/native tests include two-root/high-voltage choice,
  collapse rejection, mixed current/power loads, grouped contacts and conserved
  fields with unchanged saved-board hashes.
- Independent guided PDN checks include an approximately 11.803 MHz narrow
  antiresonance; seeded coarse samples matched a 2,001-point reference peak to
  within 1% for that declared fixture.
- The full portable PI run had 448 passes, 81 capability skips and one marker
  colour-role regression. Source/sink colour identity was restored; its focused
  follow-up passed. Later exact-source CI is the complete final regression gate.
- Current focused CLI/setup/colour/version/button contracts: 38 tests and 58
  subtests passed. Source tests intentionally separate mock API response tests,
  native saved-file checks and live editor transactions.

No original/private board was modified. Native fixtures were disposable; public
Marble was read for documentation. Capture data, assumptions, hashes and rejected
images are recorded in [the visual audit](QUICK_TOOL_VISUALS_3.6.38.md). Twenty
current opaque RGB screenshots replace stale/transparent primary displays while
older examples remain available. Extract Pins has an explicitly recorded
remaining crowded/hidden-action capture limitation; no misleading replacement
image was promoted.

## Acceptance boundaries

Native source windows are not proof of connected editor/installed lifecycle on
all OSes. Full 3D, package paths, series constant-power control, diode parallel
sharing and power-regulated transient/electrothermal/shared-return models remain
unsupported and guarded. No current convergence result qualifies constant-power
meshes automatically. Independent installers, final package checks and public
asset/feed verification are recorded with publication below.

## Final local packaging checks

All 24 PCM ZIPs passed schema, Python syntax, icons, entrypoint and SHA-256
validation. Documentation validation passed against source and packaged images.
The shared help/image/button checks passed 12 native tests. The root run completed
618 tests with 124 capability skips and one obsolete screenshot-filename
assertion; the assertion now checks the new actual capture, and all 11 suite UX
checks passed afterward. The final CI run remains the complete regression gate.

The independently extracted Quick PI installer passed all 53 native UI/solver
regressions with no skips. Its implementation modules and bundled shared runtime
matched current source bytes; its generated menu initializer is intentionally
provided by the PCM builder. Tests were staged externally, not shipped in the ZIP.

The first CI run exposed a Windows 8.3 temporary-path assertion in the new help
image test: the implementation correctly resolved the long pathname, while the
test expected its short alias. The assertion now compares the canonical image
URI. This changes the test only; final publication requires a fresh complete CI
run on the corrected source commit.
