# WayriCAD 3.6.43-beta.1

Quick EMerge 3.6.43 joins the suite as an independently installable **testing beta**. Download its PCM ZIP from the [GitHub prerelease](https://github.com/wayri/WayriCAD/releases/tag/v3.6.43-beta.1), select **Install from File** in KiCad Plugin and Content Manager, and restart PCB Editor. The stable PCM feed remains unchanged. The suite version is 3.6.43.

Quick EMerge offers patch and line templates and a saved-PCB rule-area workflow that clips two-layer copper and reviews ideal boundary ports. Native 3D and 2D views provide linked sample probes, line cuts and exports. Templates use the board as context; the rule-area workflow uses saved copper and dielectric separation. See the [user guide](../quick_emerge_plugin/README.md) for setup, dependencies and supported geometry.

The managed solver environment checks for EMerge 3+ updates and qualifies candidates with dependency checks and four coarse real solves before activation. A failed update retains the working runtime. These checks establish compatibility with the implemented workflows, not numerical convergence or coverage of all upstream capabilities.

Models use ideal PEC copper, a homogeneous lossless dielectric and ideal ports. Populated or multilayer board models, internal vias and feeds are unsupported in this workflow. Coarse API and UI smoke solves do not establish accuracy, convergence or measured validation; live KiCad toolbar operation remains unqualified in the recorded development evidence. See [validation](../quick_emerge_plugin/VALIDATION.md) and [capability coverage](../quick_emerge_plugin/CAPABILITIES.md).
