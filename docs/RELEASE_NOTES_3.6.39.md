# WayriCAD 3.6.39

Quick SI and QuickTherm gain guided studies similar to Quick PI.

| Tool | Change |
|---|---|
| Quick SI | One source/receiver and response setup, wildcard/fuzzy search, role swap, same-part pad review, explicit edge/line inputs and Apply or Apply and screen. |
| Quick SI | Exported SPICE transient directives now set the reviewed maximum internal step explicitly; output spacing and solver steps are distinguished. |
| Quick SI | Clear native model blockers and channel-coverage notes, plus bounded circuit-export timing advice in the UI and CLI. |
| QuickTherm | Heating study guide reviews included watts, cooling, steady/transient mode, readable time units and frame/storage advice. |
| QuickTherm | Power steps use actual watts; unsupported advanced profiles stay intact. Current help uses responsive native images. |
| Lumped PI/Therm reports | Sortable per-unit summaries, exact-sample slider and hover, row-to-trace selection and retained probes. Unknown limits remain unevaluated. |
| Report integrity | Saved input fingerprints, stale-input rejection and recoverable paired HTML/JSON publication. Loaded inputs can still be deliberately edited before solving. |

Updated plugin guides and main README retain existing larger previews and add
actual native captures. Numerical SI/thermal solvers are unchanged. SI peer pads
are not ideal grouped terminals; illustrative eyes are not IBIS simulations.
Spatial board heating and independent lumped component RC remain distinct.
Reviewed material, thermal capacity, cooling and channel assumptions are required.

[Validation and capture provenance](audits/SI_THERM_WORKFLOWS_2026-10-27.md).
