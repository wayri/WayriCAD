# Quick SI user guide

<img src="resources/icon-96.png" width="96" height="96" alt="Quick SI icon">

A practical guide to the capabilities shipped with WayriCAD 3.6.40. Use it with
the [feature reference](ReadMe.md), [offline help](help.html) and
[offline HTML edition](USER_GUIDE.html). Screenshots retain their actual capture
versions; they demonstrate workflows rather than measured hardware results.

## Contents

- [Choose a workflow](#choose-a-workflow)
- [Prepare the project](#prepare-the-project)
- [First path screen](#first-path-screen)
- [Read the results](#read-the-results)
- [Return paths](#return-paths)
- [Several nets and endpoint pins](#several-nets-and-endpoint-pins)
- [Inspect and cross-select](#inspect-and-cross-select)
- [Eye and step response](#eye-and-step-response)
- [IBIS and circuit export](#ibis-and-circuit-export)
- [Shunt capacitors](#shunt-capacitors)
- [Differential delay and phase](#differential-delay-and-phase)
- [Protocol suites](#protocol-suites)
- [Neighbour exposure and crosstalk](#neighbour-exposure-and-crosstalk)
- [Impedance targets and I2C](#impedance-targets-and-i2c)
- [Test points](#test-points)
- [Reports and PDF](#reports-and-pdf)
- [CLI cookbook](#cli-cookbook)
- [Troubleshooting](#troubleshooting)
- [Methods and acceptance](#methods-and-acceptance)

## Choose a workflow

| Question | Use | Output |
|---|---|---|
| Length, delay and termination? | Quick SI path screen | Connected route, section evidence and conditional estimates |
| Reference copper near transitions? | Return review / Return path tab | Sampled geometry and nearby return-via findings |
| Compare several routes? | Multi-net study | Independent cases and case-specific errors |
| Match P/N timing? | Protocol suites, Pair delay / phase | Skew, explicit-frequency phase and lane mean-delay differences |
| Investigate nearby traces? | Neighbour traces | Geometric exposure map; conditional local NEXT with model inputs |
| Explore an ideal line response? | Illustrative eye | Uniform lossless-line eye and step |
| Use device IBIS models? | Reviewed circuit export | Separate schematic to open and simulate in KiCad |
| Select I2C pull-ups? | I2C pull-ups | Permitted resistance range and candidate |
| Document/label test points? | Test point records / labels | Records or explicitly reviewed editor annotations |

Analysis is read-only. **Test point labels** is a separate annotation-write
workflow with review and **Apply to editor**. A screen, a geometric audit, a
generated circuit and an executed simulation are different deliverables.

## Prepare the project

1. Install Quick SI through the WayriCAD PCM repository and restart PCB Editor.
   See [installation](../docs/INSTALLATION.md) and
   [runtime setup](../wayricad_runtime/RUNTIME_SETUP.md).
2. Open the intended project, refill zones and save the board/project/custom rules.
   Saved-board analysis excludes unsaved edits.
3. Review enabled copper layers, dielectric thickness/Er and copper thickness.
   Missing data must remain unknown or become a clearly declared assumption.
4. Launch Quick SI from that editor. Start with one simple path before many nets.
5. Inspect the route and model basis before exporting a report.

Source CLI board operations need KiCad's native Python bindings. An editable
package install does not supply pcbnew or wxPython. Install `wayricad[si]` for
plotting and `wayricad[reports]` in the interpreter performing PDF export.
Profiles, saved-report suites, timing advice and standalone eyes can work without
reopening a board; this does not make old evidence current.

## First path screen

1. Open **Set up path and response…** in **Quick SI**. Search full net names:
   ordinary text is substring search, `*`/`?` enables wildcards and `~` fuzzy matching.
2. Select distinct Source and Receiver pads, for example `U1.1` and `J1.1`.
   Confirm direction from the schematic/device data; swap roles explicitly.
3. Enter actual driver/line inputs using the table below.
4. Confirm the real return net in **Return path (optional)** if geometric return
   review is wanted. Extra return-pin assignments are not required for that review.
5. Choose **Apply and screen**, or **Apply setup** then **Screen selected path**.
   Cancel preserves the workspace; input changes invalidate old results.
6. Review route coverage, model basis, **Needs review** reasons and next actions.

![Guided path setup](help-guided-setup.png)

This native capture uses public Marble `/ETH_PHY/MII_MDC`, `U6.8` to `U54.16`.
Its 50 Ω, effective Er 3.2, 1 ns edge, 20 Ω driver, 50 Ω receiver and 100 MHz
are explicit demonstration inputs. This is setup evidence, not a new simulation.

| Input | Units / blank behavior | Selection advice |
|---|---|---|
| Rise time | ns; default 1 ns is assumed | Use the relevant driver edge, not simply inverse bit rate |
| Frequency | MHz; default 100 MHz is assumed | Used for electrical length; distinct from data rate |
| Driver resistance | Ω; default 20 Ω is assumed | Device/corner approximation and intended series path |
| Receiver resistance | Ω; blank = ideal open | Resistive termination, not receiver input capacitance |
| Assumed Z0 | Ω; blank = extracted evidence or unknown | Justified uniform-line approximation only |
| Effective Er | Dimensionless; blank = geometry or unknown | Not automatically laminate bulk Er |
| Reference layer | Auto or explicit layer | Separate from the return-net geometric audit |
| Eye rate/swing | Mb/s and open-circuit V | Explicit NRZ demonstration inputs |

A saved physical stackup can support first-order timing across outer microstrip,
internal homogeneous dielectric and via travel. APPROXIMATE can assume ideal
continuous reference planes; it does not prove continuity or solve via reflections.
Missing/incompatible physical data remains unresolved.

## Read the results

| Quantity | Meaning / caution |
|---|---|
| Length/tracks/vias/layer changes | Selected connected path, not necessarily every branch |
| Delay / round trip | One-way propagation estimate and twice it within stated coverage |
| Electrical length | 360 × frequency × delay |
| Delay/rise ratio | The 1/6 transmission-line trigger is a heuristic, not signoff |
| Z0 and section range | Supported extracted sections or declared assumption; partial coverage is not uniform whole-route Z0 |
| Reflection | Ideal resistive `(R - Z0)/(R + Z0)` endpoint model |
| First arrival | First lossless load step, not worst overshoot or receiver margin |
| Series-match candidate | Nonnegative `Z0 - Rsource`; review topology/device limits |
| Resistance | DC/AC section estimates within the selected model |
| Needs review / coverage | Omitted geometry, materials, branches, terminals and assumptions |

HTML includes cumulative delay, section impedance and cumulative DC resistance
plots, with via positions and gaps for unknown values. A useful partial result
does not become complete by replacing unknowns with arbitrary defaults.
SCREENED, COMPLETE or a budget pass does not establish protocol compliance.

## Return paths

### Normal one-return setup

1. Choose the signal and terminals first.
2. Confirm its actual return with **Use GND** / **Use suggested return**, or
   choose it manually. Ground-like names are suggestions, not inferred connectivity.
3. Run the same path screen; **No return-path check** deliberately leaves it off.
4. Review per-layer sampled coverage, signal-via transitions, reference nets/layers
   and nearby return vias. A candidate needs contact with the local filled polygon,
   not merely the same net name or close coordinates.

![Return setup](help-return-setup.png)

This synthetic example has no filled return zone, so coverage remains unresolved.
It demonstrates the controls rather than a passing return path.

Open **More return options** for multiple return nets, optional endpoint return
pads or reference-layer override. **Find… / Ctrl+F** searches while retaining
checked items; inspect the count after filtering. Pins are not assigned automatically.

### Studies and board-wide review

For a study, select common returns and **Use this return setup for study cases**.
Optional per-case pins are cleared because endpoints differ; edit exceptions in
**Edit study cases**. Signal=return is rejected without partly updating cases.

The **Return path** tab provides board-wide return-net patterns, transition-via
radius, stub length, differential uncoupling gap and length-skew thresholds.
Choose **Analyze Board**, inspect findings/preview and **Export CSV…**.
Thresholds are engineering inputs, not universal design rules.

The route-linked review covers the whole signal net, even in a two-endpoint
screen. Sampling copper/annular contact does not solve distributed return current,
closed-loop continuity, return resistance/inductance or transfers between reference nets.

## Several nets and endpoint pins

1. Expand **Multi-net study**, search/check nets and **Add checked nets to study**.
2. **Edit study cases**: set unique IDs, exact Source/Receiver labels and direction.
   Review each row's edge, frequency, resistance, reference and optional Z0/Er.
3. Apply common returns, then edit exceptions. A study supports up to 64 independent
   source-to-receiver screens on one saved PCB/project/rules revision.
4. Run and select each case above the preview. Failed cases retain their errors;
   successful cases retain individual routes, plots and evidence.
5. Export the comparison and review incomplete/omitted coverage.

The setup guide lists other pads on the same footprint/net. **They remain separate
SI terminals**: they are not silently collapsed into an ideal two-port pin group.
Screen meaningful paths separately and inspect additional terminals, branches and
loading. A two-pad path does not model a whole multi-load bus. Circuit export has
stricter whole-net guards and rejects unresolved branches/additional terminals.
A multi-net study alone adds neither simultaneous switching nor coupled waveforms.

Adapt [independent-routes.json](independent-routes.json), replacing all placeholder
nets/pads/values. Optional directed local coupling is described below.

## Inspect and cross-select

- Wheel zooms, drag pans and Fit restores the overview. Pane dividers resize
  settings/results; expanded controls and tables scroll separately.
- **Select net on board** chooses a saved pad/via/track net. Confirm endpoint roles.
  **Probe** or Ctrl-click adds geometry coordinates; **Clear probes** removes them.
- **Select route in PCB** selects exact saved UUIDs. Ordinary preview clicks can
  select measured items through the originating editor connection.
- **Select return nets in PCB** selects checked return items; incomplete/ambiguous
  identity resolution is rejected instead of partly selecting unrelated items.
- **Use PCB selection** reads the launching editor. For several unrelated selected
  nets, choose one signal explicitly. Two selected pads alone do not define direction.
- Disabled live controls in saved/offline contexts cannot write to an unrelated editor.
  Save/reopen after source changes or identifier mismatches.

Offline route/eye/step plots support hover, click-to-pin, pan/zoom and Fit where
provided. A coordinate probe is not a solved field/voltage at that board point.
See [interaction controls](../docs/ANALYSIS_INTERACTIONS.md).

## Eye and step response

Enable **Illustrative eye**, enter NRZ rate, open-circuit swing, edge and resistive
endpoints, then screen. The ideal uniform lossless line uses resolved or explicitly
assumed Z0/delay. Native plots show sample time/voltage; click pins and right-click
clears probes. Missing samples leave gaps.

The PRBS7 eye is not IBIS, a lossy extracted channel, receiver capacitance,
jitter/BER or a protocol mask test. IBIS assignments and exported shunt capacitors
do not change this separate ideal-line eye. The standalone CLI eye below is useful
for exploring explicit hypothetical inputs without loading a PCB.

## IBIS and circuit export

1. Complete a saved-board screen/study and review **whole-net** routing coverage.
   Exactly two signal pads and accounted routing are required. Zones, branches,
   stubs, loops or disconnected copper can block export.
2. Expand **IBIS models for KiCad circuit export**. **Load IBIS…** separately for
   driver/receiver, or **Use source file for receiver** when appropriate.
3. Choose the exact Component, Pin and compatible Model. Verify the displayed
   PCB-to-IBIS mapping against manufacturer data; matching numbers are suggestions.
   Select typ/min/max corner explicitly.
4. For studies, assign both ends for every exported completed case. Failed or
   unassigned cases are reported rather than silently omitted.
5. Review duration, maximum timestep, frequency and duty cycle. **Suggest timing
   from selected routes** uses declared edges, delays and periods; it excludes
   capacitor/ESL timescales and is not convergence proof. Above two million suggested
   intervals is rejected rather than silently coarsened.
6. Leave via approximations off unless manual capacitance and **complete via-loop**
   inductance are justified. Missing copper thickness needs reviewed thickness
   and rescreening with declared uniform Z0/effective Er.
7. **Export KiCad circuit…** or **Copy circuit…** creates a new bundle. Open it in
   KiCad, inspect connections/model paths, run the native simulator and refine
   maximum timestep until relevant peaks stabilize.

The bundle contains a project/schematic, channel sheets, symbol library/table,
manifest, clipboard fragment and hashed model copies. Keep it: clipboard model
links depend on those files. Re-export for an isolated second copy; pasting the
same fragment twice reuses global signal names and connects the copies. Ideal
reference ground is shared intentionally.

Export does not execute/qualify IBIS simulation. Cases remain independent with
ideal references, without inter-net coupling or extracted via discontinuities.
See [export scope](ReadMe.md#reviewed-ibis-circuit-export).

## Shunt capacitors

In export/copy settings choose **Shunt capacitors…**. Enter a unique ID, case,
source/receiver attachment, C/ESR/ESL. UI units are **nF, mΩ, nH**; JSON uses
**F, Ω, H**. Blank capacitance is invalid. Blank/omitted ESR/ESL means ideal zero,
not inferred parasitics. Each series-RLC branch remains separate, up to 64 per
case and 256 per export.

![Endpoint capacitor editor](help-shunt-capacitors.png)

The genuine capture contains entered demonstration values, not a board simulation.
Branches connect signal → ESR → ESL → C → ideal reference. They affect **exported
KiCad/ngspice transients only**. Along-route capacitor pads, actual return loops,
bias dependence and omitted PCB loading are not inferred. A manual shunt does not
waive whole-net export guards. Inspect internal capacitor nodes and receiver
voltage and refine timestep for actual RC/LC scales.

## Differential delay and phase

1. Screen both legs in the same transmitter-to-receiver direction/revision.
2. In **Protocol suites**, add snapshots with exactly one P and N sharing the same
   Group, such as `lane0`.
3. Enter **Pair phase frequency (MHz)**, or leave blank for delay/skew only.
   Frequency is never inferred from bit rate.
4. Run and inspect **Pair delay / phase**. Choose a lane reference group or review
   the first valid alphabetical default, then export tables/evidence.

Signed skew is `tN - tP`; phase is `-360 × f × (tN - tP)` in degrees using seconds
and Hz. Thus 125 ps gives -45° at 1 GHz. Reports include absolute skew, mean delay,
unwrapped/wrapped phase and lane mean-delay differences. Intended 180° differential
inversion is excluded. Missing delay/provenance or incompatible revisions remains
unknown/blocked. Independent propagation timing is not mixed-mode/dispersive phase,
package delay, receiver crossing time or common-mode conversion.

## Protocol suites

Choose the actual interface, add route snapshots, assign roles/groups and justified
engineering budgets. A synchronous bus needs one clock and data routes per group;
for DDR DQ, its strobe may serve as clock without modeling a coupled strobe.
Use `profiles` for current IDs. USB/PCIe/DDR/Ethernet/LVDS/CAN and other profiles
organize review, not every revision's compliance simulation. M.2 alone is a form
factor: choose actual PCIe/SATA.

Budgets are maximum delay ns, skew ps, single-ended impedance error % and delay/rise
ratio. Blank evidence/needed budgets stays unknown. Defaults are not device limits.
Two single-ended impedances do not establish differential impedance by addition.
See the [profile/budget reference](../docs/QUICK_SI_PROTOCOL_SUITES.md).

## Neighbour exposure and crosstalk

### Find nearby traces

1. Open **Neighbour traces**; choose an exact net or blank for all connected nets,
   copper layer and radius mm.
2. **Map neighbours**, then search/select table rows or hover/click traces for
   closest location, edge gap, parallel overlap and coverage.
3. Narrow scope if budgets truncate the search and retain warnings in HTML/JSON.

![Neighbour exposure map](help-neighbours-3.6.38.png)

This genuine synthetic three-trace capture maps geometry: red=contact,
amber=half-radius and teal=radius. **Colour is not interference voltage**. Only
straight same-layer tracks are searched; pads/vias/arcs/zones/broadside coupling
are excluded. An empty map is not proof of no interference. Defaults include
15 seconds, 2,000 pairs and 32 optional local models.

NEXT stays UNKNOWN without explicit reference layer, center-to-plane height, Er,
copper thickness, 10–90% edge and open-circuit swing. The optional equal-width
homogeneous-plane matched-end model does not prove actual reference continuity.
**Link current study sections** associates existing directed estimates by source
hash/UUID; it does not add section peaks.

### Directed study coupling

1. Assign cases, then **Configure crosstalk pairs (optional)**.
2. Select aggressor/victim IDs; their source/receiver order determines near/far.
3. Enter edge/swing. **saved-stripline** uses supported adjacent bounding layers,
   homogeneous saved dielectric and filled coverage. **homogeneous-plane** is an
   explicit hypothetical single-plane height/Er model.
4. Run and **Review crosstalk results**. Inspect supported overlap, gaps, modal
   impedances, local step peak, panel refinement and omitted length.

Finite-thickness electrostatic BEM models supported straight parallel equal-width
sections. Saved-stripline needs adjacent reference planes, complete corridor/field
margin and no extra same-layer conductor. End margins near pads/vias/bends remain
unmodeled. Unsupported widths/materials/transitions/crossings/loading stay unresolved.
Four local ports use `R = sqrt(Zeven × Zodd)`; independent case resistances do not
apply. Equal homogeneous modal velocity gives zero FEXT **in the ideal model**,
not on the actual board. Refinement gates are numerical, not physical error bounds.
Local peaks are not added/cascaded into whole-route waveforms. Adapt
[coupled-routes.json](coupled-routes.json) and read [field limits](ReadMe.md#directed-local-crosstalk).

## Impedance targets and I2C

### Impedance & pairs

Choose a preset and review target Ω, tolerance %, frequency, primary pads,
mate/pads and reference layer. Check inferred mate names: names are not proof of
connectivity. **Analyze and validate path**, then inspect availability/error,
route/reference notes, length skew and stubs. PASS means a supported estimate
meets the chosen tolerance, not channel qualification. Live **Use PCB selection**
may be disabled in a saved-board context.

### I2C pull-ups

Enter bus voltage V, total capacitance pF (devices/tracks/connectors), maximum
rise time ns, sink capability mA and VOL maximum V. **Calculate permitted range**
reports minimum from current, maximum from rise time and an E24 midpoint candidate.
If no range exists, review actual capacitance/speed/driver rather than selecting
outside both constraints. This does not extract total bus capacitance or simulate
buffers and every device's timing specification.

## Test points

### Records and fixture draft

In **Test point records**, set descriptor field (normally `TP_Descriptor`), board
order and filters, then **Extract Preview**. Review net/descriptor, connected IC
pin/function and intermediate paths. Double-click rows to cross-select; export
CSV/Markdown/HTML. Passive traversal may include shunts, so verify against the
schematic; missing pin functions/direction remain review items.

**Export Fixture Plan** creates a channel map; **Generate Fixture PCB** creates
a separate bed-of-nails draft. Assign actual connector/probe footprints, inspect
alignment/routing and run native DRC. It does not qualify mechanical contact or
edit the source board. See [descriptor help](test_points/help.html).

### Labels and board table

1. Open **Test point labels** with its originating editor connected.
2. Set reference pattern (`TP*`) and template `{net}` or `{ref}: {net}`.
3. **Load test points**, edit proposed values and **Review changes**.
4. **Silkscreen and table options** exposes front/back values or a two-column
   editable TP/net table at entered coordinates.
5. Inspect preview and **Apply to editor** for one undo transaction. Source changes
   after preview reject the plan. **Undo last apply** requires the apply still be
   current; otherwise use native KiCad undo.

Locked/unconnected/ambiguous multi-net footprints are excluded. Offline saved
runs preview but cannot write to unrelated editors. Existing value positions/sizes
are preserved. Glyph previews are approximate: inspect actual rotation/mirroring
and silk/pad DRC. PCB values do not update schematic values and can be overwritten
by Update PCB from Schematic.

## Reports and PDF

Export HTML for readable route/eye/step figures, interaction and evidence; retain
paired JSON. Study/neighbour/suite outputs retain their own model/coverage notes.
Raw JSON stays in a disclosure. Reopen/rescreen changed sources rather than editing
hashes; outputs must not overwrite input designs/models.

Print trusted HTML after reviewing print preview, or use direct PDF below. Direct
PDF retains text/tables and embedded PNG/JPEG; canvas/SVG/unsupported interaction
is explicitly retained in HTML, not silently reproduced. It does not execute
scripts or retrieve external assets. Keep HTML/JSON alongside PDF. Install the
reports extra in that interpreter first.

```text
python -m wayricad_runtime.tool_cli report-pdf route.html --output route.pdf --evidence route.json
python -m wayricad_runtime.tool_cli report route.json --html review.html --pdf review.pdf --title "Signal review"
```

Evidence is optional and checks declared source fingerprints. Generic JSON
rendering presents recorded data without recomputation. Add `--include-raw-evidence`
to report-pdf only for a full JSON appendix. See [report details](../wayricad_runtime/REPORTS.md).

## CLI cookbook

Examples use the source-module entry point. Installed users may substitute
`wayricad-si` or `wayricad tools run quick-si --` before the subcommand. Replace
generic paths/net/pad names with inspect results. Quote hierarchical names/spaces.
Use an interpreter with the relevant native/optional dependencies.

### One route

```text
python -m signal_integrity_advisor_plugin.cli inspect C:/Projects/Example/board.kicad_pcb --net DATA --output inventory.json
python -m signal_integrity_advisor_plugin.cli screen C:/Projects/Example/board.kicad_pcb --net DATA --start U1.1 --end J1.1 --rise-ns 1 --frequency-mhz 100 --source-ohm 20 --load-ohm 50 --return-net GND --return-source U1.3 --return-load J1.3 --output route.json --html route.html
```

Omit load-ohm for ideal open load. Optional `--z0-ohm 50 --epsilon-eff 3.2` declares
assumptions, not missing-data repairs. Repeat return-net for several returns.

### Multiple routes, neighbours and ideal eye

```text
python -m signal_integrity_advisor_plugin.cli study C:/Projects/Example/board.kicad_pcb --config independent-routes.json --output study.json --html study.html
python -m signal_integrity_advisor_plugin.cli neighbours C:/Projects/Example/board.kicad_pcb --net DATA --layer F.Cu --radius-mm 1 --output neighbours.json --html neighbours.html
python -m signal_integrity_advisor_plugin.cli eye --z0-ohm 50 --delay-ns 1 --source-ohm 20 --load-ohm 50 --rise-ns 0.5 --bitrate-mbps 100 --swing-v 1 --output eye.json --html eye.html
```

Adapt the bundled study templates first. Neighbours accepts repeated net/layer,
optional `--model model.json` and source-bound `--study-report study.json`.

### Pair roles, budgets and phase

```text
python -m signal_integrity_advisor_plugin.cli screen C:/Projects/Example/board.kicad_pcb --net DATA_P --start U1.1 --end J1.1 --role P --group lane0 --output p.json
python -m signal_integrity_advisor_plugin.cli screen C:/Projects/Example/board.kicad_pcb --net DATA_N --start U1.2 --end J1.2 --role N --group lane0 --output n.json
python -m signal_integrity_advisor_plugin.cli profiles
python -m signal_integrity_advisor_plugin.cli suite --profile lvds --reports p.json n.json --max-skew-ps 20 --timing-frequency-mhz 100 --timing-reference-group lane0 --output pairs.json --html pairs.html
```

20 ps is arbitrary usage data, not an LVDS requirement. Add justified
`--max-delay-ns`, `--max-impedance-error-percent`, `--max-delay-to-rise-ratio`
budgets when needed. Never mix PCB revisions by editing report hashes.

### IBIS and circuit bundle

```text
python -m signal_integrity_advisor_plugin.cli ibis-catalog C:/Projects/Example/models/driver.ibs --output driver-catalog.json
python -m signal_integrity_advisor_plugin.cli ibis-catalog C:/Projects/Example/models/receiver.ibs --output receiver-catalog.json
python -m signal_integrity_advisor_plugin.cli timing-advice route.json --output timing-advice.json
python -m signal_integrity_advisor_plugin.cli circuit route.json --assignments assignments.json --duration-ns 100 --timestep-ns 0.1 --frequency-mhz 100 --duty-percent 50 --output C:/Projects/Example/SI-circuit-review
```

Adapt [ibis-assignments.example.json](ibis-assignments.example.json): replace hashes,
model/component/pin placeholders with catalog evidence. Relative model paths resolve
against that file. Single route case ID is `route`; studies use exact IDs.
Repeat `--case clock --case data` for subsets; output directory must not exist.
Catalog metadata is not electrical-table validation or simulator qualification.
Reviewed via fallback requires `--allow-approximations --via-capacitance-pf …
--via-inductance-nh …`; thickness uses `--copper-thickness-um` with the rescreen above.

### Touchstone and optional desktop

```text
python -m signal_integrity_advisor_plugin.cli line-network route.json --stop-hz 1000000000 --points 1001 --reference-ohm 50 --output ideal-line.s2p
python -m signal_integrity_advisor_plugin.cli network channel.s2p --to-port 2 --from-port 1 --output network.json
python -m signal_integrity_advisor_plugin.cli desktop --check
python -m signal_integrity_advisor_plugin.cli desktop C:/Projects/Example/channel.si
```

Line-network is an ideal lossless uniform two-port, not extracted board S-parameters:
source/load/loss/vias/coupling are omitted. A complete two-terminal route without
zones is required; stop frequency is Hz. Network uses optional SignalIntegrity 1.5.2
for bounded Touchstone 1.0 S data with an option line; ports are one-based.
It retains complex response, dB and phase. The upstream Tk desktop is separate,
may use `--python`, accepts trusted projects and blocks until closing. Its advanced
features are not embedded/automatically qualified in Quick SI.

### Jobsets and outcomes

Use these commands with the [shared jobset runner](../wayricad_runtime/JOBSETS.md)
for ordered steps, logs and HTML/JSON index, including native KiCad jobset invocation.
Input/model requirements remain unchanged. Suite exits: 0 within supplied budgets,
1 input/export error, 2 blocked, 3 review/incomplete. Study/neighbour REVIEW or
INCOMPLETE also returns 3. Always inspect status and coverage, not just completion.

## Troubleshooting

| Symptom | Next action |
|---|---|
| No nets / wrong project | Confirm originating editor/saved PCB and runtime; do not install unrelated pcbnew packages |
| Route unavailable | Check exact distinct endpoints, duplicate pad identities, connectivity, zones and branches |
| Unknown delay/Z0 | Review physical stackup, reference evidence and unsupported sections; enter only justified assumptions |
| Unknown NEXT | Supply supported material/reference/edge inputs; geometric colour is insufficient |
| Circuit blocked despite visible path | Check whole-net branches/stubs/terminals, thickness and via approximation guards |
| Stale result | Save/refill, reopen and rerun all compared cases on one revision |
| Slow analysis | Start with narrow nets/layers/radius and fewer cases; cancel owned jobs and inspect budget truncation |
| Controls clipped | Drag dividers, scroll tables independently and use full-name tooltips |
| Missing plots/PDF | Install si/reports extras in the actual executing interpreter |
| Circuit waveform fails | Verify model paths, native IBIS support/mapping/corner, stimulus and timestep convergence |

Saved-board workers hash PCB/project/rules before/after and before result acceptance
or export. Changing inputs, Cancel analysis or close cancels the owned job. Normal
analysis budget is 300 seconds. Legacy/live windows may be synchronous rather than
silently analyzing saved bytes. First dependency initialization is real first-run work.

## Methods and acceptance

Read [solver methods and references](ReadMe.md#solver-methods) for routed quasi-static
extraction, local BEM, ideal line response and sampled return evidence. Supporting
references include [RLC methods](../trace_impedance_plugin/ReadMe.md#solver-methods),
[IBIS 7.1](https://ibis.org/ver7.1/),
[KiCad simulator IBIS](https://docs.kicad.org/10.0/en/eeschema/eeschema.html#ibis-models)
and [ngspice](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf). A citation
does not imply every method in that reference is implemented.

- Confirm saved revision, route, endpoint roles and direction.
- Separate extracted values, entered assumptions and omitted terms.
- Review full route/net coverage, references, vias and branches.
- Use device-specific budgets and explicit phase frequency; retain unknowns.
- For circuits, inspect native connections/models, execute the simulator and refine
  timestep. Export alone is not simulation.
- Retain HTML/JSON, configurations and referenced models together.
- Use suitable coupled/channel/measurement evidence for signoff; arbitrary buses,
  full-wave fields and complete device/package/protocol behavior are not inferred.

## Blender visualization

This feature is in the updated source; existing 3.6.40 installers do not contain it.

After a supported completed study, choose **Blender…** in the main result workspace. Choose a new output folder and optionally open an installed Blender. The export includes geometry, available field data and supported computed frames. Export saved transient or other supported results through the shared CLI when they are not the main workspace result. Review [the Blender walkthrough](../wayricad_runtime/BLENDER.md) for commands, units, playback, result coverage and limits. This is visualization, not an additional numerical solve.
