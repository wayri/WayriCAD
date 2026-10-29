# WayriCAD 3.6.44-beta.1

Quick EMerge 3.6.44 is an independently installable **testing beta**. Download its PCM ZIP from the [GitHub prerelease](https://github.com/wayri/WayriCAD/releases/tag/v3.6.44-beta.1), select **Install from File** in KiCad Plugin and Content Manager, and restart PCB Editor. The stable PCM feed remains unchanged.

This beta expands the visual workbench with native 3D views, linked field probes and line cuts, reports, and additional bounded material, boundary and study controls. Saved-PCB rule-area studies use clipped two-layer copper and reviewed ideal ports; templates use the board as context. See the [user guide](../quick_emerge_plugin/README.md) and [capability coverage](../quick_emerge_plugin/CAPABILITIES.md) for supported workflows and restrictions.

New studies use 81 actual frequency samples, an 81 × 81 field grid, and 2° driven-antenna/array radiation sampling. Existing setups retain their explicit frequency and field-grid counts; the new dense preset changes those counts without changing the mesh. Views retain all stored samples, reports export 200 DPI figures, and **Help / F1** opens an offline KiCad guide covering rule areas, ideal ports, stackup, probing and troubleshooting. Local mesh refinement uses fixed public-API passes; it does not certify convergence.

The managed solver environment qualifies candidates with dependency checks and 22 compatibility checks before activation; failed updates retain the working runtime. Compatibility smoke solves do not establish numerical accuracy or convergence. Numerical convergence remains under investigation; results are exploratory and do not replace measurement or a qualified field solver. See [validation evidence](../quick_emerge_plugin/VALIDATION.md) for recorded checks and limitations.
