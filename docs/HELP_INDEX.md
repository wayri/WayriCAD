# Offline plugin help

Each independently installed package includes `help.html` and its local illustrations. Open **Help** in the plugin when available, or open that file directly from the installed package. The guides explain inputs, review/write boundaries, limitations and recovery. A source guide may contain additional CLI examples.

| Plugin | Offline workflow and troubleshooting | Source guide |
|---|---|---|
| Wayri Project Fusion | [Open local help](../project_fusion_plugin/help.html) | [Read guide](../project_fusion_plugin/README.md) |
| Analytics Studio | [Open local help](../bom_studio_plugin/help.html) | [Read guide](../bom_studio_plugin/README.md) |
| Bulk Label Editor | [Open local help](../bulk_label_editor_plugin/help.html) | [Read guide](../bulk_label_editor_plugin/ReadMe.md) |
| Component Arranger | [Open local help](../component_arranger_plugin/help.html) | [Read guide](../component_arranger_plugin/README.md) |
| Constraint Studio | [Open local help](../protocol_constraint_composer_plugin/help.html) | [Read guide](../protocol_constraint_composer_plugin/ReadMe.md) |
| Copper Balancer | [Open local help](../copper_balancer_plugin/help.html) | [Read guide](../copper_balancer_plugin/README.md) |
| Embed3D | [Open local help](../embed_3d_plugin/help.html) | [Read guide](../embed_3d_plugin/README.md) |
| Extract Pins | [Open local help](../extract_pins_plugin/help.html) | [Read guide](../extract_pins_plugin/ReadMe.md) |
| Fanout Generator | [Open local help](../fanout_generator_plugin/help.html) | [Read guide](../fanout_generator_plugin/ReadMe.md) |
| Harness and Cable Workbench | [Open local help](../harness_workbench_plugin/help.html) | [Read guide](../harness_workbench_plugin/ReadMe.md) |
| Layer Counter | [Open local help](../layer_counter_plugin/help.html) | [Read guide](../layer_counter_plugin/README.md) |
| Manufacturing Readiness Manager | [Open local help](../manufacturing_readiness_plugin/help.html) | [Read guide](../manufacturing_readiness_plugin/ReadMe.md) |
| Mechanical Check | [Open local help](../mechanical_check_plugin/help.html) | [Read guide](../mechanical_check_plugin/README.md) |
| PCB / Foil Heater Designer | [Open local help](../heater_designer_plugin/help.html) | [Read guide](../heater_designer_plugin/ReadMe.md) |
| Planar Magnetics & Actuator Workbench | [Open local help](../planar_magnetics_plugin/help.html) | [Read guide](../planar_magnetics_plugin/ReadMe.md) |
| Quick PI | [Open local help](../quick_pi_plugin/help.html) | [Read guide](../quick_pi_plugin/README.md) |
| Quick SI | [Open local help](../signal_integrity_advisor_plugin/help.html) | [Read guide](../signal_integrity_advisor_plugin/ReadMe.md) |
| QuickTherm | [Open local help](../quick_therm_plugin/help.html) | [Read guide](../quick_therm_plugin/README.md) |
| Silkscreen Label Placer | [Open local help](../silkscreen_label_plugin/help.html) | [Read guide](../silkscreen_label_plugin/README.md) |
| Trace Refiner | [Open local help](../trace_refiner_plugin/help.html) | [Read guide](../trace_refiner_plugin/README.md) |
| Trace RLC / Impedance Analyzer | [Open local help](../trace_impedance_plugin/help.html) | [Read guide](../trace_impedance_plugin/ReadMe.md) |
| Variant Manager | [Open local help](../variant_manager_plugin/help.html) | [Read guide](../variant_manager_plugin/README.md) |
| Via Stitching | [Open local help](../via_stitching_plugin/help.html) | [Read guide](../via_stitching_plugin/ReadMe.md) |

## Read a result before applying it

1. Confirm the originating project and saved/live source used by that tool. Saved-copy tools omit unsaved editor changes.
2. Start with a narrow selection or small scope, then expand after inspecting the preview. Review units, layers, side and exact net/reference names.
3. Read preserved, rejected, missing and unknown rows. An empty result or completed command does not prove that an engineering check passed.
4. Rebuild a preview after inputs or source geometry change. Use the tool’s explicit Apply/export workflow and the documented backup/undo boundary.
5. Run the native KiCad checks required by that guide. Numerical models also require their declared material, boundary and convergence evidence.

## Find a hidden or difficult control

Resize the window and expand the named options section. Scroll the settings area and the result table independently; use a table’s horizontal scrollbar for long names. Search/filter changes which rows are visible and may retain hidden checked selections. Inspect the selected-item count before a bulk action. A tooltip or details view is useful for the complete name, but it does not change the selection.

If a window remains unreadable, record the plugin name, KiCad version, display scale and the affected panel. Do not apply an unreviewed operation merely to dismiss the window. Keep the source intact and reopen the tool after correcting the display or installed package.

External research links are optional background. The workflow text and bundled images remain readable without a network connection.
