# WayriCAD 3.6.6 release notes

QuickTherm and Quick PI are updated as independent KiCad 10 PCM packages at
version 3.6.6. Other PCM packages retain their published versions and ZIPs.

QuickTherm adds an optional Gmsh/CalculiX 3D steady-conduction board model.
Select it in the native window, locate and check the `ccx` executable, then
enter or map operating power for the selected top-side components. QuickTherm
remembers the solver path locally and can prepare Gmsh in its private runtime.
The resulting checked field appears in the top/bottom board workspace with
probes and cross-selection. RθJB is optional for the board solve; without it,
package junction temperature and junction-limit status are unknown. The model
requires a fixed lower-face temperature and rejects unsupported contacts,
vias, heatsinks, convection and radiation. See the
[CalculiX model guide](../quick_therm_plugin/CALCULIX_BRIDGE.md).

Quick PI adds an optional Gmsh tetrahedral copper-volume DC model. The native
window exposes the model choice, mesh budget and a 3D result view with layer,
barrel and field filters. The complete 3D field and conservation metrics can be
exported to JSON. Its established 2.5D model remains the default, including
the series-path and HTML workflows. The 3D mode currently accepts one selected
net, ideal source/sink pads and prescribed current; it does not model AC or
electrothermal effects. See the [Quick PI guide](../quick_pi_plugin/README.md).

Install the two updated PCM ZIPs through KiCad 10 Plugin and Content Manager,
then restart PCB Editor. The independent package identifiers are
`com.github.wayri.wayricad.quick-therm` and
`com.github.wayri.wayricad.quick-pi`. First-time Gmsh setup may require access
to the configured package source. For CalculiX, the user must provide a
compatible `ccx` executable; the solver is not bundled.

Validation on Windows with KiCad 10 native Python included focused saved-board
Gmsh and CalculiX 2.23 runs, analytical DC conductor fixtures, source-hash and
energy/conservation checks, and independent PCM archive validation. These
fixtures do not qualify arbitrary board designs or physical thermal accuracy.
Native installed-plugin launch and other operating systems remain separate
acceptance checks.
