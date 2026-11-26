# WayriCAD Assistant

<img src="icon.png" width="64" alt="WayriCAD Assistant icon">

| Need | Open |
|---|---|
| Install or update | [Latest release](https://github.com/wayri/WayriCAD/releases/latest) · [Installation](../docs/INSTALLATION.md) |
| First request | [Get started](#get-started) |
| Supported actions and limits | [What it can do](#what-it-can-do) · [Implementation evidence](../docs/audits/assistant-local-orchestration.md) |
| Scripts and help | [CLI](#cli) · [Offline help](help.html) |

Describe a check or simulation in plain English. The Assistant uses local fuzzy matching, the WayriCAD action catalogue, and saved PCB net and pad identities.

## Get started

1. Open **WayriCAD Assistant** from KiCad or choose a saved PCB in the bottom pane. The net, part and pad index loads in the background.
2. Type a question in the chat. Use **Up** and **Down** to highlight a suggestion and **Tab** to insert it. A double-click also inserts it. Quoted hierarchical net names retain their spaces.
3. Review the plan and assumptions in **Plan & inputs**. Use **Edit inputs** to correct the populated settings. Reply to questions in chat, or enter missing inputs in the form. Drag the divider to give the lower pane more room.
4. For a simulation, click **Run plan** or type **run** after the plan is ready. Simple read-only checks can run immediately when **Auto-run simple checks** is enabled.
5. Read the result in chat and open files under **Results & reports**. Use **Board selection** to highlight saved copper and navigate to the originating PCB Editor.

Try **Quick PI voltage drop at 3.3 V from J1.1 to U1.1 with 250 mA**, **Quick SI route delay at 100 MHz from J1.1 to U1.1, rise time 1 ns, driver 25 ohms**, or **Thermal board heat map with U1 at 0.5 W and ambient 25 C**. Replace the references with pads or parts on your board.

The Assistant can use a unique shared pad net and resolve a component to a unique pad on the selected net. Duplicate sheet-local names and multiple matching pads require a choice. It asks for physical operating conditions such as load current, temperature, or driver rise time. For coupled or advanced models, supply the reviewed native study JSON.

## What it can do

The command catalogue exposes specific existing CLI actions, including electrical checks, mechanical review, board analytics and transmission-line calculations. Use the CLI `capabilities` command for the exact supported actions and required inputs in your installed version. Every plugin is not automatically controllable: actions must be explicitly registered with a parameter schema and an execution adapter.

### Simulation and analytics requests

| Ask for | Supply or review |
|---|---|
| "Give me the number of 10u capacitors" | A saved project or root schematic. Defaults to the base variant. Counts fitted BOM references with the requested R/C/L prefix and normalized nominal value; unparseable values are listed, not counted as matches. Saved native inputs only; unsaved or Analytics Studio workspace overlays are not included. |
| "Give me layer wise total copper area" | A saved PCB. Shows union area in mm² and coverage by layer. Missing zone fill or unsupported geometry can make totals unknown; save filled zones in KiCad before measuring. |
| "Solve board heat map at 25 C with C1=0.5 W and C2=0.1 W" | Explicit dissipated watts. Steady thin-sheet screen with automatic mesh and declared still-air/material defaults; no junction estimate. Separate transient component RC and 3D solid actions use reviewed native study JSON. |
| PI two-port AC impedance, coupled DC bundle or series-path solve | Supply the corresponding reviewed study JSON. Series also needs source voltage and load current. Draft power-tree and series-path discovery can run directly on the saved board; edit and save paths in Quick PI. |
| SI multi-net and crosstalk study | Supply the saved PCB and reviewed Quick SI study JSON. Single-route screening still accepts conversational inputs. |
| "List EMerge examples", then "Run EMerge research example" | Choose an exact built-in example ID and a saved PCB context; the example geometry is independent of that PCB. The qualified solver must already be prepared. The report preview shows the sampled S matrix and key RF results. Use the optional solver override to choose PARDISO when the selected runtime supports it. Open the full report for geometry, radiation and mesh evidence. Custom PCB-region and array setup remain in Quick EMerge. |

### Quick PI batch and load-step examples

- **Multi-net DC.** With a saved PCB selected, ask **Quick PI batch: net 3V3 from J1.1 to U1.1 at 3.3 V with 500 mA, net 1V8 from J1.2 to U1.2 at 1.8 V with 200 mA**. Use your actual net and pad names. Quote names containing spaces. Each case uses automatic mesh and runs against the same saved board. For shared returns, multiple load groups per case, or different solver settings per rail, ask **Quick PI batch study "rails.json"** and supply a reviewed Quick PI batch file.
- **Transient.** Ask **Set up a Quick PI transient** and enter the lumped inputs in **Plan & inputs**, or include values in the request. For example, **Quick PI transient source voltage 3.3 V, source resistance 50 mOhm, source inductance 100 nH, initial current 200 mA, step current 1 A, step time 1 ms, path resistance 20 mOhm, path inductance 10 nH, capacitance 100 uF, ESR 10 mOhm, duration 2 ms, time step 1 us**. Supply an explicit zero for an omitted parasitic you want modeled as zero. The model uses one load and an aggregate capacitor. For multiple loads, individual shunt capacitors or a finite ramp, use **Quick PI transient study "transient.json"** with the reviewed native setup. The PCB can supply provenance and a saved pad label. It does not supply the circuit R/L/C.

Review the plan, run it, and open the HTML report for all cases or the time plots. The native result JSON is also available.

The Assistant window uses its current Python environment. Select **EMerge
runtime…** and choose the prepared interpreter to run Quick EMerge in its
own environment for this window. From the command line, review the saved plan
and use
`python -m suite_assistant_plugin run PLAN --output-root RESULTS --python SOLVER_PYTHON`.
The required dependencies must already be present in that interpreter (including
Shapely for saved copper measurements); this workflow does not install them.
Open the original reports or the originating tool for full field data and plots.
Use `capabilities` for the current catalogue. For guard stitching, selected signal
nets may supply the route scope, but the guard net is a separate required input.
For example: **“Guard signal net CLK with guard net GND, spacing 2 mm and offset
1 mm.”** The result is a preview plan; apply reviewed copper in Via Stitching.

| When this happens | What to do |
|---|---|
| More than one action matches | Choose the offered interpretation. |
| A net, source, material or numerical setting is missing | Fill in the requested inputs; the Assistant does not silently assume them. |
| No supported action matches | Rephrase around a specific check or open the relevant plugin directly. |
| A tool or dependency is unavailable | Follow the error and that plugin’s runtime setup instructions. |
| A run is taking too long | Click **Cancel**; cancellation is forwarded to the worker. |

The model limits of the underlying tool still apply. A generated report is evidence of the specified screening calculation, not a substitute for material, source/sink or mesh validation. The Assistant does not change components, annotations, tracks, zones or board geometry. Generated reports and run records are written to a separate results folder.

## Results in the window

In **Results & reports**, select an output and toggle **Preview selected report**.
The Assistant shows HTML summaries and tables, the first supported plot,
routing drawings, and tables from JSON or CSV. AC two-port and planar PDN
previews include complex impedance samples. DC requests with return nets show
the solved outgoing rail and a separate return geometry review. Use **Open selected report** for large outputs,
PDFs, interactive graphs, and complete result data.

![Native Assistant chat showing a completed Quick PI run](help-assistant.png)

The native capture uses the public Pocket KiView example PCB on Windows with KiCad 10.0.6. It shows the Quick PI DC result after the user supplied the missing load current in chat and ran the plan.

## CLI

```text
wayricad-assistant capabilities
wayricad-assistant plan "Quick PI voltage drop at 3.3 V from J1.1 to U1.1 with 250 mA" --board C:/Projects/Example/board.kicad_pcb --output C:/Projects/Example/plan.json
wayricad-assistant run C:/Projects/Example/plan.json --output-root C:/Projects/Example/results
```

Use KiCad's Python for saved PCB inventory and native solvers. Portable Python can still plan with explicit names. Include missing inputs with `--answers` using question keys such as `0.current`.

## Implemented methods, execution boundary and evidence

| Method | Inputs and result | Implementation and limits |
|---|---|---|
| Local intent ranking | A request is tokenized into words and character n-grams, then compared with registered action phrases to produce a ranked typed action. | [`_words`, `_grams`, `_similarity`, `_rank`](../wayricad_runtime/assistant.py). This fuzzy matcher is deterministic local string scoring, not an LLM, semantic proof or unrestricted agent. Ambiguous top choices are returned for user selection. |
| Slot extraction and clarification | Explicit numeric/unit phrases, selected nets and safe saved-board context populate an action schema; missing or invalid required fields become questions. | [`_slots`, `_safe_context`, `propose`](../wayricad_runtime/assistant.py). Only declared schema fields are accepted; domain defaults and limitations come from the selected tool adapter. |
| Typed compilation and plan sealing | Each step compiles through an allowlisted action adapter into an argument array; canonical JSON is SHA-256 sealed. | [`_compile`, `_seal`, `validate_plan`](../wayricad_runtime/assistant.py). The seal detects plan modification between review and execution; it is not a digital signature or authorization credential. Arbitrary code/shell strings are not generated. |
| Source freshness | Relevant board/project/hierarchy inputs are discovered and hashed before execution; the worker revalidates the plan and sources. | [`_source_paths`, `_input_hashes`, `run_plan`](../wayricad_runtime/assistant.py). Unsaved editor state is outside this evidence boundary. |
| Isolated execution and report provenance | A non-daemon worker process executes registered tool CLIs, supports cancellation, captures bounded logs and records step/artifact hashes in a run report. | [`run_plan`](../wayricad_runtime/assistant.py). Scientific meaning and validation remain those of each invoked tool; orchestration does not upgrade an estimate to proof. |
| Safe result/UI boundary | Only supported report extensions inside the returned output root are opened; board selection invalidates old plans and editor navigation rechecks the saved-board hash. | [`report_path`, `_show_result`, `_show_in_editor`](gui.py) and [`analysis_selection.py`](../wayricad_runtime/analysis_selection.py). These contracts are covered by [`test_assistant_ui.py`](tests/test_assistant_ui.py); wx/native tests may skip outside KiCad. |

### Technical background

- The [KiCad IPC add-on documentation](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/) defines the running-editor integration used for navigation and selection. It does not validate tool results.
- Python's [`hashlib`](https://docs.python.org/3/library/hashlib.html) documents the SHA-256 primitive used for plan/source/artifact freshness. Intent ranking and clarification are project algorithms documented from source, not claims attributed to external AI research.
