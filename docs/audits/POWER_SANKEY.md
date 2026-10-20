# PI and thermal power-flow diagrams

Validated on Windows with Python 3.14 and the installed KiCad 10.0 Python/wx
runtime. These are read-only accounting views of retained solver evidence;
adding a diagram does not change the numerical solve or PCB.

## Accounting contracts

Quick PI connects solved source power to delivered load-unit power and modeled
losses. Multiple pads belonging to an ideal unit are counted once. Shared-return
studies pool their sources and count common return loss once, without inventing
per-rail loss attribution. An explicit independent loop includes both supply
and return losses. A plain rail includes only its modeled supply-path losses.
Nonconserving, incomplete or unsupported evidence produces an explanation.
Infeasible or unaccepted operating points retain their diagnostic status.
Steady electrothermal budgets show cold/hot results separately; a DC diagram
does not represent transient stored energy.

QuickTherm connects known scoped component powers and separately retained
copper/contact Joule sources to total known dissipation. Contact heat-transfer
rates and heat-balance totals are not added again. Missing or excluded powers
remain explicit omissions, not zeros. The diagram describes the saved
steady/reference operating point, not instantaneous playback power or
environmental heat rejection. Large studies group small sources while retaining
their individual values in the source table.

The shared SVG renderer uses one linear watt-to-width scale throughout each
graph. Node label padding is independent of flow width. SVG hover titles work
without JavaScript; embedded JavaScript adds keyboard-accessible pinned probes.
All assets are offline. Source-hash and overwrite protection applies when
publishing standalone views as well as normal report exports.

## Checks performed

| Check | Evidence |
|---|---|
| Shared renderer, PI and thermal accounting/export tests | 24 passed; includes actual analytical-strip FEM results, multi-pad units, multiple loads, common-return conservation, unknown/invalid powers, imported Joule sources, dense source aggregation, stale export rejection and escaped labels. |
| Root regression suite | 494 passed, 88 skipped; skips remain unverified capabilities. An initial subprocess-profile cleanup failure passed after directing test temp directories into the workspace. |
| Native PI actions and existing report workflows | New button/stale-source check and batch UI checks passed; 32 report/batch/volume tests and nine electrothermal workflow/report tests passed in the native runtime. |
| Native thermal reports and action | 18 accounting/report/budget tests passed before the final shared publication check was added. The native workflow invoked the Sankey button, checked its generated 0.5 W document and invalidation, and preserved source bytes. Browser launch was mocked. STEP loading was disabled for that focused UI run; the separate STEP-enabled workflow timed out in FreeCAD loading. |
| Saved Marble results | Rendered and visually inspected actual SVG diagrams: PI source 0.24 W with approximately 0.23772164 W delivered and 0.00227836 W modeled loss; four declared thermal component inputs total 8.3 W. These reuse the assumed operating points in the [Marble study](MARBLE_COUPLED_ANALYSIS.md), not new measured-board validation. |
| Probe interaction | Executed the embedded scripts with DOM test doubles; hover, click, keyboard pinning and clearing passed. This is not a full browser integration test. |
| Independent PCM payloads | Built 23 disposable packages, checked schemas/actions/assets/runtime syntax, and exported both diagrams from isolated PI and Therm payloads with their bundled shared renderer. |

See the [PI README](../../quick_pi_plugin/README.md#source-to-sink-power-flow)
and [QuickTherm README](../../quick_therm_plugin/README.md) for controls and limits.
Candidate packages were not published over an existing release.
