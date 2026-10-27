# WayriCAD 3.6.40 — in development

Individual shunt capacitors can participate in transient studies.

Reports gain a consistent HTML layout and a direct optional PDF exporter. Saved
JSON results from any tool can be rendered as HTML/PDF tables; existing analysis
HTML retains its embedded raster figures in PDF. Interactive-only views are
explicitly identified. Quick SI adds P/N delay, skew and explicit-frequency phase
matching, plus inter-pair mean-delay comparison in the UI, CLI and reports.
Quick PI adds two-point DC voltage probes on solved 2.5D copper, with A/B markers,
saved report readings and read-only CLI probing. Unrelated cases and unsolved
regions are rejected; full-volume and AC/transient waveform probing remain outside
this feature.

Quick PI now opens on **All copper layers (projected)** with a separate **Silk**
toggle off by default. Explicit layer choices survive new results. Vias use short
V1/V2 labels across probes and reports; mesh cells use C1/C2 labels. Original
selection IDs remain in the evidence. Analytics exports retain their script-free
HTML contract while using the shared report styling and static navigation.

[Report workflow and static-PDF limits](../wayricad_runtime/REPORTS.md).
[Validation and model boundaries](audits/REPORTS_AND_DIFFERENTIAL_PROBES_2026-10-27.md).

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
