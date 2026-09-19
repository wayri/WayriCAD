# WayriCAD Trace, Via and Plane RLC

Inspect an existing connected route or a filled zone between two terminals. The local preview shows actual pads, copper, vias and filled islands. The section table records each layer transition, reference layer/net and model.

## Native analysis views

![Trace RLC path inspection on Berkeley Marble](help-marble-path.png)

Actual saved-board path inspection, including layer transitions. Per-segment estimates and unresolved reference coverage should be reviewed before interpreting a single global impedance.

![Plane and zone analysis view](help-marble-plane.png)

Plane/zone estimates use the stated geometry and return assumptions; this is not a full-wave field solution. The installed [offline help](help.html) explains the available modes.

## Workflow

1. Save and refill the PCB in KiCad, then launch the plugin. The PCM action opens a saved-board snapshot; reopen it after saving further changes. Choose a net and two different pads. Native in-editor use can also synchronize from PCB selection.
2. Choose **Path** for existing trace/via/zone connections, or **Zone/plane** for a selected filled island and an assumed current-corridor width.
3. Leave the reference at **Auto**, or choose a copper layer explicitly.
4. Analyze, inspect the geometry and section status, then export the results.

Auto ground recognition uses names such as GND, AGND, DGND and VSS. A name alone does not establish a reference: the engine checks filled copper coverage on adjacent copper layers. Explicit reference selection still requires copper coverage. Unfilled zones must be filled in KiCad first.

Paths follow existing layer transitions through vias and plated pads. Analysis does not shift or reroute the board's copper. Crossings on different layers are not connections. Zone links require a finite-width corridor inside one filled island; holes and disconnected islands cannot be crossed by a shortcut. Complex current paths around obstacles and trace arcs remain unresolved. Automatic path search omits islands with more than 128 contacts; use terminal-defined zone mode for those islands.

## What the numbers mean

| Geometry | Estimate |
|---|---|
| Trace | DC conductor resistance; skin-effect estimate; closed-form microstrip or symmetric stripline L/C/Z0 where the reference geometry supports that model |
| Via | Barrel resistance with assumed 25 Âµm plating and isolated partial inductance; capacitance remains unknown without antipad geometry |
| Zone/plane | Terminal-corridor resistance and inductance; capacitance from filled-island/reference overlap and stackup separation |
| Trace + zone + via | Connected path and individual section models; unresolved terms remain identified |

Plane R/L depends on the selected terminals and assumed corridor width. It is not a spreading-resistance solution. Full-island capacitance and corridor R/L are different estimates and must not be interpreted as one series RLC circuit. Mixed routes have section impedances; they do not have a single uniform Z0. Partial totals contain modeled sections only. Disconnected endpoints produce an unresolved result instead of an aggregate-net fallback.

The stackup source, copper thickness, dielectric separation and permittivity are recorded. A manufacturing document can disagree with embedded board data; resolve that discrepancy before using these estimates for design decisions. Models exclude copper roughness, etch shape, solder mask, dielectric loss, pad and thermal-spoke impedance, full return-current distribution, and connector/package effects. Critical high-speed work needs field simulation or measurement beyond this preliminary geometry analysis.

## Read-only CLI

Run with KiCad 10's Python, from this repository or with the wheel installed:

```powershell
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m trace_impedance_plugin.cli inspect board.kicad_pcb --net MDI0_P
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m trace_impedance_plugin.cli path board.kicad_pcb --net MDI0_P --start U1.1 --end J1.1 --output route.json
& 'C:/Program Files/KiCad/10.0/bin/python.exe' -m trace_impedance_plugin.cli zone board.kicad_pcb --net +3V3 --start C1.1 --end C2.1 --zone-id '<ID from inspect>' --corridor-width-mm 0.2 --output plane.json
```

Replace the example net/pad/zone identifiers with those returned by `inspect`. `wayricad-rlc` is the installed entrypoint. JSON contains numeric values, source-board SHA-256 and section status. Exit codes: 0 resolved, 1 input/runtime error, 2 disconnected (also argparse usage errors), 3 partial. Reports use a separate `.json` file and never save the source board.

See the [Marble smoke report](../docs/audits/MARBLE_SUITE_SMOKE.md) for measured coverage and limitations. KiCad 10 is the native geometry target; KiCad 11 operation requires validation against its available native geometry API.

Model references: [TI Analog Engineer's Pocket Reference](https://www.ti.com/seclit/eb/slyw038d/slyw038d.pdf) for the approximate via inductance relation; [Analog Devices PCB layout guidance](https://www.analog.com/en/resources/analog-dialogue/articles/high-speed-printed-circuit-board-layout.html) for plane-overlap capacitance. These references do not validate this implementation against measurements.
