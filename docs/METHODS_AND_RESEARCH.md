# Implemented methods and research guide

This guide covers the 24 active packages at **v3.6.32**, source commit
`7d8aa79b` (including the 3.6.32 IBIS export and thermal playback changes).
Each plugin README documents its
material algorithms, source locations, assumptions, limits and existing
verification evidence. Package directory names can differ from display names.

## How to read the references

- **Implemented method:** code evaluated by the supported workflow. A paper
  does not imply every formula or accuracy claim in it is implemented.
- **Backend or format reference:** an external mesher, solver, API or file
  format used by the workflow; optional backends retain their declared scope.
- **Background or input provenance:** theory, vendor guidance, material data
  or project policy. These do not establish measured performance.
- **Verification evidence:** analytical checks, conservation, refinement,
  regression fixtures or recorded native runs. Existing tests are linked for
  traceability; this documentation edit does not imply fresh solver runs.

Several layout and project tools use bespoke bounded heuristics. Their READMEs
identify these directly rather than assigning an unsupported research pedigree.
Extracted facts, entered assumptions, inferred candidates and unknowns remain
distinct. DRC/ERC, numerical verification and physical validation establish
different things.

## Plugin methods

| Tool | Methods, sources and evidence |
|---|---|
| Analytics Studio | [README](../bom_studio_plugin/README.md#implemented-methods-provenance-and-validation) |
| Bulk Label Editor | [README](../bulk_label_editor_plugin/ReadMe.md#implemented-methods-and-evidence) |
| Component Arranger | [README](../component_arranger_plugin/README.md#implemented-methods-and-research-basis) |
| Copper Balancer | [README](../copper_balancer_plugin/README.md#implemented-methods-and-research-basis) |
| Embed3D | [README](../embed_3d_plugin/README.md#implemented-methods-provenance-and-validation) |
| Extract Pins | [README](../extract_pins_plugin/ReadMe.md#implemented-methods-and-evidence) |
| Fanout Generator | [README](../fanout_generator_plugin/ReadMe.md#implemented-methods-and-research-basis) |
| Harness and Cable Workbench | [README](../harness_workbench_plugin/ReadMe.md#implemented-methods-and-evidence) |
| PCB / Foil Heater Designer | [README](../heater_designer_plugin/ReadMe.md#implemented-methods-and-research-basis) |
| Layer Counter | [README](../layer_counter_plugin/README.md#implemented-methods-and-research-basis) |
| Manufacturing Readiness Manager | [README](../manufacturing_readiness_plugin/ReadMe.md#implemented-methods-release-evidence-and-limits) |
| Mechanical Check | [README](../mechanical_check_plugin/README.md#implemented-methods-and-research-basis) |
| Planar Magnetics & Actuator Workbench | [README](../planar_magnetics_plugin/ReadMe.md#implemented-methods-and-research-basis) |
| Project Fusion | [README](../project_fusion_plugin/README.md#implemented-methods-identity-and-merge-evidence) |
| Constraint Studio | [README](../protocol_constraint_composer_plugin/ReadMe.md#implemented-methods-numerical-scope-and-evidence) |
| Quick PI | [README](../quick_pi_plugin/README.md#solver-methods) |
| QuickTherm | [README](../quick_therm_plugin/README.md#solver-methods) |
| Quick SI | [README](../signal_integrity_advisor_plugin/ReadMe.md#solver-methods) |
| Silkscreen Label Placer | [README](../silkscreen_label_plugin/README.md#implemented-methods-and-research-basis) |
| Assistant | [README](../suite_assistant_plugin/README.md#implemented-methods-execution-boundary-and-evidence) |
| Trace RLC / Impedance Analyzer | [README](../trace_impedance_plugin/ReadMe.md#solver-methods) |
| Trace Refiner | [README](../trace_refiner_plugin/README.md#implemented-methods-and-research-basis) |
| Variant Manager | [README](../variant_manager_plugin/README.md#implemented-methods-identity-and-transaction-evidence) |
| Via Stitching | [README](../via_stitching_plugin/ReadMe.md#implemented-methods-and-research-basis) |

## Shared implementation and validation

Shared code is linked from the tools that use it, including routing, package
conduction, thermal RC advancement and jobset/report orchestration. Installed
packages vendor required shared code; the source links do not introduce
sibling-plugin runtime dependencies. See [runtime setup](../wayricad_runtime/RUNTIME_SETUP.md).

Read [PI analytical benchmarks](PI_REFERENCE_BENCHMARKS.md),
[package conduction assumptions](PACKAGE_CONDUCTION.md),
[compatibility evidence](COMPATIBILITY.md) and the plugin-specific validation
links before interpreting results. A completed calculation alone does not
establish hardware qualification, protocol compliance or manufacturing acceptance.
Future capabilities require corresponding implementation and evidence before
being described as implemented.
