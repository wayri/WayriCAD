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
- Updated offline help, user guides and a repeatable native acceptance tool
  cover source and independently installed plugin validation.

## Evidence And Limits

The public thermal demo and real KERO Encoder PCB passed the normal native
window/worker Run flow using illustrative powers and ambient only. Source PCB
hashes stayed unchanged. The Encoder thin-sheet run modeled 0.6 W with a
3.33e-16 W heat-balance residual. This is execution/conservation evidence, not
measured thermal accuracy or stackup-resolved validation. Junction temperatures
remain unknown without package data.

The new automatic-mode native regression passed. A broad native run recorded
323 passes and 3 skips; follow-up native checks still have two unresolved UI
timeouts. Hosted CI, final native rechecks, installed-payload verification and
asset receipts are release gates, not completed claims. See the
[detailed validation record](../quick_therm_plugin/ONE_CLICK_VALIDATION.md).

This release candidate follows the separate 4.8.7 viewer update. Neither prior
release assets nor the public PCM feed are replaced during candidate testing.
