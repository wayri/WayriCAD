# Quick EMerge capability coverage

This inventory describes **development source**, beyond the published
3.6.43-beta.1 package. Upstream baseline: EMerge **3.0.0b9**, inspected at
[446232037d175a596606c6c9ea986e372560566f](https://github.com/FennisRobert/EMerge/commit/446232037d175a596606c6c9ea986e372560566f).
The [upstream project metadata](https://github.com/FennisRobert/EMerge/blob/446232037d175a596606c6c9ea986e372560566f/pyproject.toml)
requires Python 3.10-3.13. This is a bounded integration, not every upstream
API or arbitrary user-supplied EMerge scripting.

| Area | Implemented development scope | Limits and evidence |
| --- | --- | --- |
| Native KiCad regions | Saved two-layer polygon/holes, actual clipped copper, saved dielectric separation, reviewed boundary ports, source custody | 1-8 ideal ports; no general multilayer, drilled-inside/via-barrel, populated-component or interior-feed extraction. Native geometry tests and real synthetic-region solve; see [workflow](README.md#simulate-a-pcb-rule-area-enclosure). |
| PCB/antenna templates | Inset patch with optional bounded external feed and signed Y offset, microstrip, internal four-layer stripline with two vias, finite patch arrays | Templates do not import board copper. Via template is separate from native-region extraction. |
| Materials | PEC or finite conductor, conductivity/thickness/roughness; dielectric loss tangent and linear frequency-dependent permittivity | Explicit simplified models; no general spatial-property editor, coating/material library or measured-loss qualification. |
| Boundaries and meshing | ABC order 1/2, PEC, PMC, PML; mesh size/tetrahedron guards; supported driven adaptivity | API smoke coverage does not establish boundary independence or convergence. Other study modes require supported linear/no-adaptation settings. |
| Periodic | Floquet periodic patch with incidence/polarization | Bounded unit-cell setup, not arbitrary periodic CAD or unrestricted higher-order diffraction. |
| Scattering and CAD | PEC sphere/STEP and GDS, GDS+XML, Gerber+plated Excellon, ODB adapters; plane-wave excitation | Reviewed recipe, units/materials and source-file manifest required. Expert import path, not a complete visual import wizard. All four fabrication adapters executed real coarse scattering solves. |
| Waveguide | Rectangular TE10 reference-plane study | Bounded geometry/mode. Independent cutoff/propagation reference checked; not a multimode port-design workbench. |
| Finite arrays | Full multiport FEM response, progressive phase and coherent excitation/radiation | Up to nine ports. Independent complex-field superposition checked; coarse meshes do not qualify deep nulls, gain or efficiency. |
| Components/optimization | Ideal FEM mid-line shunt R/L/C; bounded parameter search using real solves | No populated component library or unrestricted optimizer. Search budget/mesh may limit the answer. |
| Thermal | Steady/transient substrate conduction; dielectric RF-loss heating | Pinned-b9 compatibility adapter; independent slab/time-step references checked. No copper surface heating, general conjugate heat transfer or arbitrary multiphysics. |
| Fields | Complex E/H sampling; E/H/power-flow magnitude; thermal K; XY plane, bounded Z stack and point-cloud view | Maximum 17 layers/100,000 samples. Recorded frequency/excitation; no automatic recomputation on chart selection or arbitrary continuous-volume probe. |
| Native inspection | VTK 3D; 2D plots; navigation, linked original-sample probes, pins/extrema/nearest-sample profiles, CSV | Component tests and physical gestures are distinct acceptance scopes. No measured frame-rate or every-GPU compatibility claim. |
| RF networks | Full solved matrix, magnitude/phase/group delay/impedance/Smith diagnostics, renormalization, mixed mode, port termination, ideal RLC embedding, AAA/vector fit, Touchstone | Derived networks are separate evidence; original EM fields do not change. No out-of-band/passivity guarantee from a fit. |
| Exports/reports | Source-checked offline HTML and PDF reports; charts/probes/derived-network evidence; exact planar-sheet DXF; official Optycal-compatible far-field MsgPack | Live exports limited to supported driven/array models. Numeric MsgPack protocol/readback, not an installed Optycal GUI. PDFs need ReportLab. |
| Runtime updates | New isolated candidate, dependency consistency, 22 real compatibility checks, atomic activation and rollback | Latest 3+ is a candidate, not automatically supported by its version string. Optional accelerators require separate hardware/runtime qualification. |

## Qualification boundary

On 2026-10-29, the current adapter completed **22 real checks** under EMerge
3.0.0b9/SuperLU, including the advanced studies, four fabrication imports,
network fitting and live DXF/Optycal readback. Certificates bind the installed
version to the exact adapter/qualification source. The checks establish API
execution and result contracts; they do not establish numerical convergence
or portability to arbitrary future releases.

See [validation evidence](VALIDATION.md) for the runtime, exact check list,
reference checks and remaining acceptance work. General native PCB extraction,
measured antenna verification, optional solver hardware, arbitrary imported
geometry and live host integration require their own evidence.
