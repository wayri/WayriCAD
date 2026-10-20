# Command line access to all WayriCAD tools

Install the complete WayriCAD wheel for the unified CLI, or run from this source checkout with its dependencies. Independently installed PCM plugins do not imply that every other tool is installed in their Python environment.

```text
wayricad tools list
wayricad tools show quick-pi
wayricad tools doctor
wayricad tools run quick-pi -- --help
wayricad tools run quick-si -- --help
```

`wayricad-tools` and `python -m wayricad_runtime.tool_cli` provide the same interface. `list`, `show` and `doctor` print JSON. `run` preserves the selected backend's stdout, stderr and exit code; arguments are passed as an argument list without a shell. The registry accepts fixed tool IDs, not arbitrary modules or commands.

For native board operations, select a prepared interpreter explicitly **before** the tool name:

```powershell
wayricad tools run --python 'C:/Program Files/KiCad/10.0/bin/python.exe' silkscreen -- preview board.kicad_pcb --refs U1 R1 --output labels-preview.json
```

The runtime needs the dependencies of the selected operation. `doctor --python PATH` checks Python plus the availability of pcbnew, wxPython, NumPy and SciPy without loading a PCB or opening a GUI. It does not qualify an entire solver installation. Individual tool help states its additional runtime requirements.

## Available headless interfaces

The commands below expose the existing headless workflows. They do **not** imply CLI parity with every GUI action; PCB-writing tools retain their preview, candidate-output and explicit-apply contracts.

| Tool ID | Headless workflow | Detailed command help |
|---|---|---|
| `bom-studio` | Analytics Studio: fields, BOM, variants, analytics and pipelines | `wayricad tools run bom-studio -- --help` |
| `bulk-label-editor` | Headless JSON parameters: bulk-label.preview; GUI write operations are separate | `wayricad tools run bulk-label-editor -- --help` |
| `component-arranger` | Group, preview, validate and export placement | `wayricad tools run component-arranger -- --help` |
| `copper-balancer` | Preview and export copper balance changes | `wayricad tools run copper-balancer -- --help` |
| `embed-3d` | Project-local libraries and 3D models | `wayricad tools run embed-3d -- --help` |
| `extract-pins` | Inspect, extract pins, reports and diagrams | `wayricad tools run extract-pins -- --help` |
| `fanout-generator` | Settings, preview plan and reviewed candidate export | `wayricad tools run fanout-generator -- --help` |
| `harness-workbench` | Headless JSON parameters: harness.build; GUI write operations are separate | `wayricad tools run harness-workbench -- --help` |
| `heater-designer` | Headless JSON parameters: heater.analyze; GUI write operations are separate | `wayricad tools run heater-designer -- --help` |
| `layer-counter` | Preview and export copper-layer counters | `wayricad tools run layer-counter -- --help` |
| `manufacturing-readiness` | Headless JSON parameters: manufacturing.audit; GUI write operations are separate | `wayricad tools run manufacturing-readiness -- --help` |
| `mechanical-check` | Saved-board mechanical screening and solid inspection | `wayricad tools run mechanical-check -- --help` |
| `planar-magnetics` | Headless JSON parameters: magnetics.analyze; GUI write operations are separate | `wayricad tools run planar-magnetics -- --help` |
| `project-fusion` | Analyze and merge saved projects | `wayricad tools run project-fusion -- --help` |
| `protocol-constraints` | Headless JSON parameters: protocol-constraints.compose; GUI write operations are separate | `wayricad tools run protocol-constraints -- --help` |
| `quick-pi` | DC copper conduction, explicit returns and independent rail studies | `wayricad tools run quick-pi -- --help` |
| `quick-therm` | Board/component temperature screening and thermal reports | `wayricad tools run quick-therm -- --help` |
| `signal-integrity` | Route screening, return paths and independent multi-route studies | `wayricad tools run signal-integrity -- --help` |
| `silkscreen-label-placer` | Read-only placement preview and settings; apply remains in the GUI | `wayricad tools run silkscreen-label-placer -- --help` |
| `trace-impedance` | Trace, differential-pair and filled-zone RLC estimates | `wayricad tools run trace-impedance -- --help` |
| `trace-refiner` | Preview, validate and export refined traces | `wayricad tools run trace-refiner -- --help` |
| `variant-manager` | Variant inventory and reviewed batch operations | `wayricad tools run variant-manager -- --help` |
| `via-stitching` | Settings, preview plan and reviewed candidate export | `wayricad tools run via-stitching -- --help` |

Aliases include `analytics`, `quick-si`, `rlc`, `silkscreen`, `constraint-studio` and `fusion`.

## JSON parameter workflows

Bulk label preview, harness generation, heater and magnetics analysis, manufacturing metrics and protocol-rule composition accept a JSON parameter object. The `show` command lists each tool's fixed control method. The method cannot be changed by the request document.

```json
{"pattern":"R*","replacement":"RES_*","values":["R1","R2","C1"]}
```

Save that object as `labels.json`, then run:

```text
wayricad tools run bulk-label-editor -- --request labels.json --output label-preview.json
```

This generates a preview, without writing PCB labels. Output must be a new JSON file. Duplicate JSON keys, unsupported method selection and source/report aliases are rejected. Other parameter contracts are documented in the [CLI guide](CLI_USER_GUIDE.md) and `wayricad capabilities`.

## Multi-net analysis and return paths

PI and SI studies require explicit terminal assignments for each case. Their batch execution shares source provenance, not current, temperature or crosstalk between nets. Optional PI return-conduction cases solve a declared single-load supply/return loop; this is distinct from a geometric return-path audit. Review the per-case model and limitations before interpreting aggregate totals.

```text
wayricad-pi board.kicad_pcb --batch pi-study.json --output pi.json --html pi.html
wayricad-si study board.kicad_pcb --config si-study.json --output si.json --html si.html
```

Use the plugin guides for study schemas and examples: [PI](../quick_pi_plugin/README.md), [SI](../signal_integrity_advisor_plugin/ReadMe.md) and [Therm](../quick_therm_plugin/README.md).

To run all three as a project-local report sequence, supply reviewed study/configuration files:

```text
wayricad jobs init board.kicad_pro --preset analysis-studies --set pi_study=pi-study.json --set si_study=si-study.json --set thermal_config=thermal.json
wayricad jobs validate board.kicad_pro
wayricad jobs run board.kicad_pro
wayricad jobs jobset board.kicad_pro --output analysis.kicad_jobset
```

A project and its saved PCB must exist. The job runner creates separate step directories and records failures; report generation is not electrical or thermal sign-off. Batch failures and incomplete model coverage remain visible in their JSON/HTML evidence.

## Silkscreen preview

```text
wayricad-silkscreen settings
wayricad-silkscreen preview board.kicad_pcb --refs U1 J1 TP1 --settings silk.json --output labels.json
```

Silkscreen CLI planning is read only, keeps source hashes, reports proposed positions, sizes, rotations and guide paths, and retains unresolved labels. It uses a bounded native subprocess and supports a timeout. Applying labels remains in PCB Editor, where active project rules and native DRC must be checked. A command completing successfully is not a guarantee that all labels fit.
