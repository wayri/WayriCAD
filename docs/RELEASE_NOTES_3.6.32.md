# WayriCAD 3.6.32

QuickTherm now provides finer control over transient playback. Quick SI can
load source/receiver IBIS models and export selected complete routes as editable
native KiCad simulation circuits.

| Tool | Change |
|---|---|
| QuickTherm | Default 10 s studies with computed frames every 0.1 s; separate solver maximum step and output interval, Previous/Next and 0.25×/1×/5×/20× playback. Requested frame times and switching events are solved, not invented by visual interpolation. Explicit storage limits guide larger studies. |
| Quick SI | Load `.ibs` files, select component/pin/model/corner for each endpoint, reuse the source file for the receiver, and retain assignments while switching study cases. |
| KiCad circuit export | Export all checked complete paths in one bundle, or create the bundle and copy a flat native circuit ready for Schematic Editor. Vendor model copies, simulation properties, timing and provenance are included. |
| CLI | `wayricad-si ibis-catalog` lists reviewed choices and file SHA-256; `wayricad-si circuit` exports explicit route/study assignments with repeatable `--case`. |

Keep the exported model bundle after pasting: clipboard model links point to it.
Separate exports receive unique signal-net names; pasting the same fragment twice
shares its global names. Re-export for an isolated copy. Ground is common.

Circuit export supports complete, single-ended point-to-point networks. Branches,
stubs, uncovered copper and automatic signal-zone models are rejected. Vias need
explicit reviewed loop inductance/capacitance; missing copper thickness needs
explicit thickness, assumed Z0 and effective permittivity. The circuits use an
ideal reference and do not include inter-net coupling or full frequency-dependent
board loss. Quick SI's existing eye remains an ideal-line preview; use KiCad's
simulator for the native IBIS response.

Two public Marble paths, each about 253 mm with three vias, produced a combined
144-component circuit. Native SPICE/XML counts and connectivity matched, with
zero ERC violations. Stock IBIS models were synthetic integration fixtures,
not models of Marble's actual ICs. A separate synthetic native transient yielded
6,718 finite samples over 400 ns. See [methods and checks](audits/IBIS_CIRCUIT_EXPORT_2026-10-26.md)
and [release validation](audits/RELEASE_3.6.32.md).

Refresh WayriCAD in KiCad Plugin and Content Manager, install updates and restart
PCB Editor. All 24 packages advance: IPC packages 3.6.32; Trace Refiner 0.3.5,
Fusion 0.9.15, Variant Manager 0.6.8, Component Arranger 0.1.7,
Layer Counter 0.1.7 and Silkscreen Placer 0.3.7.
