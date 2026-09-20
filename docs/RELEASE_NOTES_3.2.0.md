# WayriCAD 3.2.0

This release consolidates the suite into 16 independently installable plugins and improves visual review before analysis or editing. Packages remain marked testing.

- **BOM Studio:** three primary views, retained templates and bulk editing, and simple grouped/individual exports with test-point and DNP conditions. Separate test-point and DNP lists include staged edits without changing templates or source files.
- **Quick PI:** retains the native net, mesh and result views, source/sink markers and local 2.5D DC analysis. Decoupling placement analysis is now a tab in the same window.
- **Quick SI:** integrates return-path review and test-point records. A new editor previews test-point values against net names and builds a silkscreen table; live edits use stale-board checks and an undoable transaction. The illustrative PRBS eye/step screen is included in the release, with explicit uniform lossless-line assumptions.
- **Protocol suites:** Quick SI adds 33 selectable interface profiles from I2C/SPI/UART through DDR and PCIe, explicit pair/bus groups, timing budgets, reference coverage and optional eye-rate checks. Native route/eye review and offline CLI/HTML/JSON retain unknown models; these are engineering screens, not certification.
- **Trace RLC:** actual copper can be coloured by layer, DC/AC resistance contribution or model coverage. Section selection highlights geometry. AC sweeps include plated-via loss, continuous sheet skin diffusion, inspection and CSV export. Changed inputs clear stale plots and disable exports.
- **Magnetics:** dimensioned cores, measured B-H interpolation, saturation/current sweeps, transformer volt-second screening and reduced magnetic-circuit force estimates. Read-only STEP import shows solid volume, bounds and wireframe. A separate linear axisymmetric triangular FEM model visualizes field/mesh for an annular winding and optional cylindrical or annular core, with energy inductance and convergence checks.
- **Copper Balancer:** clearer density range, remaining deficit, over-target regions and rejection reasons, with stricter geometry and numeric validation.
- **Mechanical Check:** optional quick 2D envelope screening without FreeCAD, with native geometry feedback. Exact STEP checks remain available; a quick screen cannot provide 3D mechanical sign-off.
- **Manufacturing Readiness:** includes footprint pad drills, plated-pad annulus and slots; absent objects report N/A. Custom-anchor and offset-hole bounds are conservative; insufficient or unsupported geometry reports UNKNOWN and blocks manufacturing release export.
- **Constraint Studio:** visual worksheet, rule matrices/sets and per-layer width/gap profiles retain native custom-rule output, staging and undo.
- **Corpus fixes:** improved PI triangle quality and bounded plane meshing; indexed return-path audits; actionable SI blockers with no invented missing dielectric defaults; restored the bundled return-path helper in automation ZIPs. [Native corpus evidence](https://github.com/wayri/WayriCAD/blob/develop/docs/audits/KICAD_MONKEY_FIX_FEEDBACK.md) retains unconverged peak-current and incomplete-model limits.
- Current guides and local help include new screenshots. Legacy standalone PDN, Return-Path, Test Point and Design Variant packages leave the active feed/wheel. The installer backs up their existing installations; source is retained for reference.

## Scope and interpretation

PI remains a 2.5D DC copper-conduction solver, not full 3D or AC electromagnetic simulation. RLC one/two-face curves compare imposed current-excitation assumptions; arbitrary proximity, roughness and edge crowding remain unresolved. Zone RLC uses a stated current corridor. SI eye plots are illustrative and do not provide IBIS, coupled crosstalk or protocol certification.

Magnetic field FEM supports the explicit axisymmetric linear geometry only. Imported arbitrary STEP solids are inspected, not meshed for a full field solution. B-H circuit analysis and ideal-gap force are separate reduced models; no arbitrary transformer or nonlinear full-field/Maxwell-stress claim is made.

The known KiCad 10 Windows shared-TEMP IPC collision still requires distinct editor temporary namespaces where it occurs; `tools/open_kicad.py` provides that workaround. Windows native checks do not establish native macOS/Linux or KiCad 11 compatibility.
