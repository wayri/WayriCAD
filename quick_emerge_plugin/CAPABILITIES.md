# EMerge capability inventory

This inventory records upstream EMerge **3.0.0b9**, inspected at commit
[446232037d175a596606c6c9ea986e372560566f](https://github.com/FennisRobert/EMerge/commit/446232037d175a596606c6c9ea986e372560566f)
on 2026-10-28. It is a beta snapshot, not evidence that every later 3.x or 4.x
release has the same API. The upstream package requires Python 3.10 through
3.13 ([project metadata](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/pyproject.toml)).
The inventory describes upstream functionality, not a claim that Quick EMerge
exposes, validates, or supports every feature.

## Quick EMerge scope

The application offers parametric patch/line templates and a saved-PCB rule-area
workflow. The latter imports native polygon-clipped two-layer copper, preserves
concave boundaries/holes, uses saved dielectric separation, and reviews ideal
ports at actual rule-area cuts. Native tests and real EMerge/SuperLU service/UI
solves cover that bounded path. Drilled features inside the crop, multilayer and
populated models, interior feeds and unsupported cut interfaces are blocked or
unimplemented; general PCB import is not claimed. Templates retain context-only
board identity. Numerical accuracy/convergence still needs qualification. The
remaining capabilities below are **upstream or planned**, not implemented UI
features. No general-purpose arbitrary EMerge scripting interface is exposed.

## Upstream capabilities and integration status

| Area | Upstream evidence and scope | Quick EMerge status |
| --- | --- | --- |
| Native KiCad rule-area studies | Saved board rule-area UUIDs, filled copper, polygon clipping and explicit stackup evidence; see [development guide](README.md#simulate-a-pcb-rule-area-enclosure). | Implemented two-layer bare-copper enclosure/port review, real solves, S-matrix, original-coordinate field probing, and source/geometry custody. General multilayer/via/component support remains planned. |
| Solid and planar CAD | Primitives, operations, coordinate systems, selections, open regions and PML are exported in [core.py](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/src/emerge/core.py); [STEP example](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo17_step_import.py). | Adapter constructs fixed templates; arbitrary CAD editing/import planned. |
| PCB construction | PCB routing, layer stacks, vias and port construction are illustrated in the [stripline example](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo6_striplines_with_vias.py). Arbitrary board outlines and generating board/air/vias are described in the [changelog](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#pcb). | Adapter constructs a parametric line; arbitrary board geometry planned. |
| Fabrication and layout import | Gerber/Excellon FileBasedPCB, GDSII, GDS stack XML and ODB++ import are described in [file import and export](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#file-import-and-export); ODB++ requires `emcad`, CAD extras are optional. | Planned. A KiCad board is not yet converted to a solver model. |
| Materials and physical attributes | Frequency and coordinate-dependent material properties, conductor properties, thickness, roughness, coatings and voids; see [core.py](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/src/emerge/core.py) and [physical attributes](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#physical-attributes-and-automatic-boundary-conditions). | Template uses a real dielectric and PEC conductors; lossy, dispersive and detailed material assignment planned. |
| Excitations and boundaries | Lumped, modal and Floquet ports, lumped elements, scattering excitation, absorbing boundaries and PML are represented upstream; see [boundary conditions](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#boundary-conditions-and-ports) and [periodic example](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo7_periodic_cells.py). | Template-specific lumped ports and absorbing boundary; selectable boundary/port setup planned. |
| Mesh and sweeps | Gmsh mesh controls, AURA adaptive mesh refinement, frequency sweep and adaptive AAA sweep; see [meshing and adaptivity](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#meshing-and-adaptivity). | Mesh controls, optional adaptive refinement and AAA sweep controls are implemented; convergence qualification remains necessary. |
| Solvers | Direct CPU solver choices include PARDISO, UMFPACK, SuperLU and platform-specific Accelerate; SPARTA supports CPU, GPU and hybrid modes and cuDSS supports NVIDIA GPUs with optional dependencies. Availability depends on platform and installation; see [README](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/README.md#direct-solvers) and [solver changes](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#solvers). | Explicit solver chooser is implemented; optional solver modes and thread controls are planned. |
| Periodic and arrays | Periodic cells and scan angles in [demo 7](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo7_periodic_cells.py); finite-array tiling/layout is explicitly experimental in the [changelog](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#experimental). | Planned. |
| Networks | Sampled and fitted S-parameters, port renormalization, differential/common-mode combination, external component embedding and Touchstone export are covered by [post-processing](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#post-processing). | Full template S-matrix, reflection metrics and sampled Touchstone export are implemented; other network operations planned. |
| Near and far fields | Mesh interpolation, external near field, domain sampling, current and Poynting traces, far-field and multiple-port far-field are documented in [post-processing](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#post-processing) and [patch example](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo4_patch_antenna.py). | Template plane sampling and patch far-field output are adapter targets; arbitrary probes, currents and field operations planned. |
| Scattering and RCS | Scattered-field excitation and radar cross-section workflow are illustrated in [RCS example](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo22_RCS.py). | Planned. |
| Optimization and exports | Upstream optimizer supports SciPy methods and DIRECT, with examples in [demo 20](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/examples/demo20_optimization.py); DXF, Touchstone and Optycal exports are listed in [changelog](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#file-import-and-export). | Optimization and these formats planned; plugin result persistence is separate. |
| Thermal and experimental | Upstream includes thermal steady/transient operations and experimental domain decomposition; see [solver section](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#solvers) and [experimental section](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#experimental). | Planned; no coupled thermal qualification is implied. |

## 3.x migration and verification boundary

The dependency manager automatically installs a first-open runtime and checks
for newer non-yanked EMerge 3+ releases daily. Candidate environments must pass
dependency checks and all four real adapter smoke solves before atomic
activation; failure retains the working runtime, and a compatible predecessor
can be restored. Compatibility certificates bind the installed EMerge version
to the exact adapter source. This does not qualify unexposed capabilities or
guarantee that arbitrary future releases remain compatible.

The [upstream migration guide](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/CHANGELOG.md#2-breaking-api-changes)
records changed PCB layer-index arguments, port creation, import paths, mesh
and refinement arguments, and far-field return types and array order. Its
far-field results use public `E` and `H` accessors; `farfield_3d` arrays are
indexed theta then phi. A version string alone does not establish compatibility
with later versions. Each supported runtime and solver path needs an actual
end-to-end test and numerical convergence/reference evidence. This inventory
was derived from upstream source and documentation. A real EMerge 3.0.0b9
SUPERLU line-model smoke run completed at three frequencies; that run does not
numerically qualify the model, optional solvers or advanced controls.
