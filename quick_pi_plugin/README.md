# WayriCAD Quick PI

Quick PI estimates DC voltage drop and current flow through saved PCB copper. It uses the board's filled copper polygons, pads, holes, layer thicknesses and plated via barrels to build a layered finite-element conduction model. Analysis runs in a cancellable worker process and does not edit the board.

## Workflow

1. Save the PCB and update zone fills in KiCad. Open **WayriCAD Quick PI**.
2. Choose a net, source pad and sink pad. Enter source voltage in volts and load current in amperes.
3. Click **Run analysis**. The **Net**, **Mesh** and **Results** tabs show the same extracted geometry.
4. Choose a copper layer and result: absolute voltage, voltage drop, DC transfer resistance (drop divided by load current), current density, current flow, loss density or pulse risk. Drag to pan and scroll to zoom; **Fit** restores the copper extent.
5. Use **Export report** for an offline HTML report with seven maps of the selected layer and a paired JSON file containing all layers and numerical results.

![Quick PI on the Berkeley Marble board](help-workflow.png)

**Mesh and material options** contains mesh size, assumed via plating, copper temperature, ambient temperature, pulse duration and a temperature limit. A smaller mesh costs more time and memory. Compare successive mesh sizes before relying on localized peaks. The default 25 µm plating is an assumption, not a measured board property.

## Console

Expand **Console** to enter commands. `help`, `nets`, and `pads <net>` list available names. **Tab** cycles context-aware completions; **Up/Down** recall commands. Commands run through the same cancellable worker as the controls; the pane does not execute Python or shell commands.

```text
run pi "Net-(R161-Pad1)" U1.M6 R161.1
```

The console also accepts explicitly defined series components. Use `help` for the supported resistance/inductance syntax. Component links are drawn as dashed lines and recorded in the report; they are not invented board tracks. Source voltage, load current and material settings come from the visible controls.

## Reading results

- **Copper ΔV/I** is conductor resistance for a single-net run. **Circuit ΔV/I** includes explicit series components. Operating-point source **V/I** is displayed separately.
- Current-flow arrows indicate in-plane direction. Sheet current is A/mm; volumetric sheet and barrel current density is A/mm². Via barrels have their own current, resistance and loss records.
- Density and pulse-risk maps color the plated via barrel around its white drill hole. The color scale includes both sheet and barrel values. Each layer shows the worst barrel segment crossing that layer; coincident segments are combined without adding their risk values.
- The pulse-risk map compares adiabatic deposited energy with energy to reach the chosen temperature limit. It excludes heat spreading, cooling, phase change and fuse-opening dynamics; it is not a fuse-time prediction.
- Floating copper has no solved potential. Geometry extraction and meshing issues are reported rather than silently connecting disconnected islands.
- This is a **2.5D DC conduction model**, not an AC, electromagnetic or thermal field solver. Explicit inductance does not change the DC solution. Contact-current peaks depend on mesh refinement and terminal assumptions.

## Runtime and installation

Install the WayriCAD PCM ZIP through KiCad's Plugin and Content Manager, or use the suite's documented manual installation. KiCad 10's native Python needs NumPy, SciPy, VTK, Matplotlib and wxPython. The UI uses Matplotlib's wx canvas when available and a native wx/Agg canvas when the optional wx SVG backend is missing. Everything renders locally.

The Berkeley Marble smoke test used `Net-(R161-Pad1)`, source `U1.M6`, sink `R161.1`, 1 V and 1 A. The tested mesh produced approximately 2.568 mV drop. This is a regression example, not validation against a physical measurement.
