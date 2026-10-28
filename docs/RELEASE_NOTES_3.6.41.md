# WayriCAD 3.6.41

Quick PI, Quick SI and QuickTherm spend less time preparing and solving studies.
The release also includes Blender export and expanded, illustrated user guides.

| Tool | Changes |
|---|---|
| Quick PI | Faster first inspection, vectorized 3D mesh/solver preparation and field display. Joule feedback opens a guided materials and cooling page using the selected terminals; advanced model inputs remain available. |
| Quick SI and Trace RLC | Reuse geometry queries and net indexes within each operation, avoid unnecessary scientific-runtime imports and speed up differential-pair detection. |
| QuickTherm | Exact spatial indexing reduces multilayer geometry work. Linear transient steps reuse matrix factors and fixed-boundary coupling. Manual example configurations work through the CLI. |
| All three Quick tools | Blender export of supported geometry and computed results, including stored thermal frames. Expanded control references, CLI recipes, model limits and genuine Marble/White Rabbit illustrations. |

## Recorded performance

These are local before/after measurements, not guarantees for every board or machine.

| Case | Before | After | Result comparison |
|---|---:|---:|---|
| Fresh Quick SI analysis, Marble | 7.086 s | 3.771 s | Identical serialized result |
| Fresh Quick SI analysis, White Rabbit | 1.520 s | 0.515 s | Identical serialized result |
| Marble multilayer thermal solve | 93.072 s | 65.020 s | 131,815 numerical values identical |
| Linear thermal transient benchmark | 0.21145 s | 0.06967 s | Maximum temperature difference 1.07 × 10⁻¹⁴ °C |
| PI 3D field preparation benchmark | 0.0809 s | 0.0182 s | Same field preparation contract |

Native meshing, file loading and graphics still contribute to startup time.
Full SI window timings were noisy; a quiet paired run improved from 13.517 to
12.421 seconds. Solver speedups do not imply equivalent gains for every UI action.

## Guides and examples

- [Quick PI guide](../quick_pi_plugin/USER_GUIDE.md) and [control reference](../quick_pi_plugin/CONTROL_REFERENCE.md).
- [Quick SI guide](../signal_integrity_advisor_plugin/USER_GUIDE.md).
- [QuickTherm guide](../quick_therm_plugin/QUICK_THERM_USER_GUIDE.md).
- [Marble and White Rabbit source revisions and walkthroughs](QUICK_TOOL_EXAMPLE_BOARDS.md).
- [Blender workflow](../wayricad_runtime/BLENDER.md).

## Limits to keep visible

PI's coupled thermal backend still rejects plated slots and nonplated holes.
The Marble Joule input is a diagnostic reproduction, not a successful coupled
temperature result. A separate explicit steady Joule example converges and
generates reports. QuickTherm's broader drill support does not apply to PI coupling.

White Rabbit's imported board lacks a qualified physical stackup. Tutorials
retain that diagnostic rather than invent fabrication data. PI transients use
explicit lumped circuits; capacitor proximity review does not optimize placement.
Blender visualizes supplied computed states and does not add solver accuracy.

See the [PI](audits/QUICK_PI_3D_SPEED_2026-10-28.md),
[SI](audits/QUICK_SI_SPEED_GUIDE_2026-10-28.md),
[thermal](audits/QUICKTHERM_SPEED_GUIDE_2026-10-28.md) and
[Blender](audits/BLENDER_VISUALIZATION_2026-10-28.md) validation records.
