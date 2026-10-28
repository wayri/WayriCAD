# Blender visualization verification

Date: 2026-10-28. Platform: Windows; native KiCad 10.0.6 / Python 3.11.5 /
wxPython 4.2.2; Blender 5.2.0 LTS. This is a source update, not a replacement
of the already published 3.6.40 installers.

## Implemented workflow

Quick PI, Quick SI and QuickTherm expose an explicit **Blender…** result action.
The shared chooser selects a new folder, scalar field and optional installed
Blender executable. Export and optional launching run outside the UI thread.
The shared CLI exports complete saved JSON results and can build a `.blend` or
PNG headlessly. No installation, remote upload or solve occurs during export.

The bundle contains bounded, data-only scene JSON, a fixed importer, instructions
and SHA-256 manifest. Existing destinations are rejected. Saved board/study
fingerprints, nested cases and result-file custody are checked; changed inputs
are rejected. Input values are never evaluated as Python code. The Blender
script is optional and imported lazily; normal plugin startup does not load bpy.

## Geometry, quantities and time

| Source | Supported representation | Limits |
|---|---|---|
| PI | Actual sheet triangles or tetrahedral boundary faces; potential, voltage drop, current-density magnitude or cell dissipated power | Cell power is not boundary heat flux. No new AC or transient field is inferred from DC. Complete embedded batches only. |
| SI | Saved straight track-section ribbons; delay, impedance or resistance estimates | Vias, arcs and zone paths are omitted with notes. Missing physical Z is drawn coplanar and reported. No traveling-wave animation is invented. |
| Thermal | Saved grid cells/layers, component estimates, stored spatial and component-node frames | Unknown/absent cells are not filled. Display retains the numerical model's subcell and package limitations. |
| Lumped transient | Computed quantity-versus-time curves, including pre/post-event samples at equal timestamps | Curves are not assigned invented spatial positions on a board. |
| Context | Saved outline, cutout and drill contour walls; available saved component triangles or footprint envelopes | Envelopes have illustrative 0.5 mm heights. Contour extrusions are display context, not a qualified mechanical model or blind/backdrill reconstruction. |

PCB millimetres map to Blender metres as `(x, -y, z) / 1000`, with face winding
reversed after reflection. Fields sharing name and unit use one scale over all
objects and frames. Unknown values are gray. Field, board and component
collections can be toggled independently; PI/SI approximate envelopes start as
wireframe and are excluded from renders.

Field animation uses one Blender frame per union of computed stored times,
with exact physical-time markers and held states. PNG atlas sequences retain
animation after saving/reopening without executable handlers or auto-run text.
Playback at 24 fps is presentation speed, not a uniform physical timestep.

Budgets include 128 MiB JSON, 200,000 faces, 400,000 vertices, five million
scalar values, 1,000 stored times, 1.2 million mesh corners and 4,096 atlas files.
The importer additionally bounds values after union-timeline expansion.

## Saved Marble results

Existing illustrative saved results were exported; these were not new numerical
simulations. The source PCB SHA-256 remained
`482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
No original or private project was modified.

| Saved result | Exported objects / faces | Export preparation | Blender import, save and PNG render |
|---|---|---|---|
| PI | 1,008 / 40,474 | 2.823 s | Succeeded; final context-collection structure also checked natively |
| SI, four routes | 1,011 / 38,926 | 2.557 s | 6.040 s |
| Thermal | 1,008 / 94,786 | 1.180 s | 7.352 s |

Timings are local single runs, including the stated steps; they are not a
cross-machine benchmark. Native optional context extraction does not extract
all-board copper or rerun a mesh solver.

The public [thermal render](../images/blender-marble-thermal.png) uses four assumed
sources: U1 5 W / 5 K/W RθJB, U35 2 W / 8 K/W, U23 0.5 W / 10 K/W and U54
0.8 W / 10 K/W, at 25 °C ambient in the saved air study. Materials and cooling
remain declared assumptions. Board and junction scales are distinguished. The
render was inspected at 1200 × 900. Filename stamps were disabled and PNG
metadata checked for local paths before publication; no data or pixels were
retouched. Earlier task-local renders retain their original private metadata
and are not publication assets.

## Verification

- Focused tests exercise adapter values/units/topology, nulls, physical return
  signs, tetrahedron boundary removal, spatial node maps, stored events, source
  privacy, budgets, overwrite protection, duplicate JSON keys, changed sources,
  result custody, manifest checks and optional launching.
- Final shared root suite: 698 tests, 574 passed and 124 skipped. Focused Blender
  suite: 48 passed. Native chooser/destination tests: six passed.
  Existing PI startup, SI setup and Therm guided/whole-board checks passed. One
  thermal test timed out while importing an unrelated Sankey dependency in a
  combined run; its isolated retry passed without modifying the test.
- Real Blender imported and rendered all three saved Marble result types.
  A synthetic two-state thermal fixture was exported with the final pipeline,
  saved, reopened and rendered at its last frame. It retained exact 0 s / 1 s
  markers, two relative texture sequences, two frames and zero automatic text
  scripts. A separate 45 °C / 100 °C fixture confirmed common scale and distinct
  colors with one field legend.
- Source help links, images, guide structure and compilation are checked.
  A real Marble current-density export also completed in a native background
  worker while the main wx event loop continued processing (3.482 s).
  No claim is made that this validates every GUI workflow, every Blender version
  or the physical accuracy of the underlying solver models.

Task-local validation outputs are approximately 48 MiB, retained for reproduction;
no dependency download, new runtime or full checkout was created. Existing
published assets and PCM feed were not changed.

See [the user walkthrough](../../wayricad_runtime/BLENDER.md) for operation and
unsupported cases.
