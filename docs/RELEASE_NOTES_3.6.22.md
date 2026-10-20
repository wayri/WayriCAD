# WayriCAD 3.6.22

Automatic mesh sizing, power-flow diagrams, shared-return PI and local SI
crosstalk are now included in the independently installable KiCad packages.

## Quick PI

- **Automatic mesh** recommends a background size and grades the layered mesh
  near supported tracks, contacts and via lands. Manual sizing remains available.
  The CLI accepts `--auto-mesh`; reports retain sizes, budgets and unresolved features.
- Multi-net studies can jointly solve declared common return copper. Multiple
  physical pads can form one source or load unit; its total current is counted once.
- **Power flow** opens an offline source-to-sink Sankey. HTML reports include
  delivered load power and modeled losses, counting shared-return loss once.

## QuickTherm

- **Automatic mesh** recommends the base grid and refines actual multilayer
  intervals near heat sources and contacts. Sources take priority under tight
  budgets; small unresolved features remain visible in the results and reports.
- **Dissipation Sankey…** shows individual parts and retained copper/contact
  Joule inputs flowing left to total known dissipation on the right. Unknown
  powers are omissions, not zeros. CLI HTML exports include the diagram.
- Automatic/manual controls, CLI `--auto-mesh`, request settings and offline
  guides use the same supported model contracts.

## Quick SI and documentation

Directed aggressor/victim studies now report local coupled-line fields and
NEXT/FEXT for supported straight equal-width sections. Reports preserve omitted
lengths, branches, vias and unsupported geometry. Solver-method tables and
linked references were added to PI, SI, Therm and RLC documentation.

## Limits

Mesh recommendations are geometry heuristics, not error estimates or convergence
certificates. PI volumetric and thermal CalculiX sizing remain manual. Thermal
thin-sheet automatic sizing is uniform; layered mode supplies local refinement.
SI crosstalk is not a cascaded whole-route or whole-bus simulation. Shared-return
PI remains fixed-current, fixed-temperature DC; it does not add shared
electrothermal feedback or AC return fields. Review each model's assumptions.

## Install

Refresh the WayriCAD repository in KiCad Plugin and Content Manager, install
updates and restart PCB Editor. Alternatively use **Install from File** with
the desired PCM ZIP; do not unpack it.

All 23 packages carry the current shared runtime. The 17 IPC packages are
3.6.22; native package versions are Fusion 0.9.11, Variant Manager 0.6.4,
Silkscreen Labels 0.3.1, Trace Refiner 0.2.3, Component Arranger 0.1.3 and
Layer Counter 0.1.3. Existing published assets remain unchanged.

[Validation](audits/RELEASE_3.6.22.md) ·
[PI guide](../quick_pi_plugin/README.md) ·
[Thermal guide](../quick_therm_plugin/README.md) ·
[SI guide](../signal_integrity_advisor_plugin/ReadMe.md)
