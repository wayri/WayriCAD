# WayriCAD 4.8.8

## QuickTherm Automatic Run

- New windows enable Automatic setup. Enter component dissipation and click Run;
  the built-in solver and automatic mesh are selected from supported saved
  board geometry. No CalculiX installation is required for normal screening.
- A supported physical stackup selects the layered model. Otherwise a labelled
  thin-sheet screen is used without inventing stackup dimensions.
- Blank starting material and ambient values are filled with documented
  illustrative defaults. Edited values and explicit component scope survive.
- Explicit model/manual-mesh actions leave automatic mode. Old saved studies
  retain their advanced choices through backward-compatible migration.
- Unknown selected powers, unsupported layer-dependent physics and conflicting
  boundaries remain actionable errors, not silent model substitutions.
- Native test launches isolate stdin from invalid Windows handles, retain
  UTF-8 diagnostics and correctly replace the startup plot before selection
  assertions. Bounded traceback capture preserves useful timeout evidence.
- Updated offline help, user guides and a repeatable native acceptance tool
  cover source and independently installed plugin validation.

## Evidence And Limits

The public thermal demo and real KERO Encoder PCB passed the normal native
window/worker Run flow using illustrative powers and ambient only. Source PCB
hashes stayed unchanged. The Encoder thin-sheet run modeled 0.6 W with a
3.33e-16 W heat-balance residual. This is execution/conservation evidence, not
measured thermal accuracy or stackup-resolved validation. Junction temperatures
remain unknown without package data.

The complete native QuickTherm suite passed **326 tests and 223 subtests**, with
three optional CalculiX/Gmsh integration skips. Both previously failing native
UI checks passed without relaxing their assertions or increasing timeouts.
The attached release receipt identifies final hosted CI, immutable assets and
installed-payload verification separately. See the
[detailed validation record](../quick_therm_plugin/ONE_CLICK_VALIDATION.md).

This release follows the separate 4.8.7 viewer update. Prior release binaries
remain immutable; feed promotion occurs only after new assets are verified.
