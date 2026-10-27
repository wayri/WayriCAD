# WayriCAD 3.6.40 — in development

Individual shunt capacitors can participate in transient studies.

| Tool | Capability |
|---|---|
| Quick PI | Per-load banks retain each C, ESR and ESL. Banks replace aggregate C/ESR, with no double counting. |
| Quick PI | Finite-rise prescribed current ramps support realistic inductive branches. Ideal steps that require impulse voltages are rejected. |
| Quick PI | Review two-pad capacitor candidates on an explicit signal/return pair; edit saved capacitance suggestions, ESR and total connection ESL. |
| Quick PI | Inspect each capacitor's internal voltage, branch current, ESR loss and time-refinement evidence in the native workspace and HTML/JSON reports. |
| Quick SI | Add editable source/receiver capacitor branches to exported KiCad/ngspice schematic and clipboard circuits. CLI assignments support the same branches. |

PI uses an explicit lumped ideal-return model, with bounded work and conservation
checks. It does not extract capacitor placement, DC-bias curves, package/routing
parasitics or converter control. Coupled electrothermal bank stepping is not
supported. SI additions apply to supported endpoint circuits; the built-in
illustrative eye and arbitrary along-route/multi-terminal topology remain outside
this feature. Existing coverage guards stay active.

[Workflow, model checks and capture provenance](audits/SHUNT_CAPACITORS_2026-10-27.md).
