# Jobsets and automatic reports

Run repeatable report sequences from KiCad 10's **Job Sets** tab, the terminal, or CI. The same configuration drives all three. Each run creates a fresh project-local folder, an HTML report index, a JSON summary, per-step logs, and SHA-256 hashes for generated files.

## Quick start

Install the WayriCAD wheel into the Python environment used for automation. PCM installs individual GUI plugins; it does not install the suite's command-line entry points into your terminal. Native electrical analysis additionally needs KiCad 10's Python bindings and the documented scientific runtimes.

From your project directory:

```text
wayricad-jobs init Example.kicad_pro --preset fabrication
wayricad-jobs validate --config wayricad-jobs.json
wayricad-jobs run --config wayricad-jobs.json --keep-going
```

`wayricad jobs ...` and `python -m wayricad_runtime.jobs ...` are equivalent entry points. If the directory contains exactly one project, `init` can detect it automatically. Existing configurations are never overwritten.

Open `reports/wayricad/latest.html` to see the latest completed run. Each earlier run stays in its own timestamped directory. **PASS means the commands returned zero and produced their required files; it does not certify the board or the numerical model.** DRC/ERC violations, incomplete SI/RLC results, and PI convergence failures keep their nonzero status.

## Use the native KiCad sequence editor

1. Create and validate the report configuration above.
2. Generate a native jobset:

   ```text
   wayricad-jobs jobset --config wayricad-jobs.json --output WayriCAD.kicad_jobset
   ```

3. In KiCad Manager, open **Job Sets**, then open `WayriCAD.kicad_jobset` from the project tree. The generated **Special: Execute Command** job runs the report sequence. Leave **Ignore exit code** disabled.
4. Place it before or after your native Gerber, drill, drawing, BOM, or other jobs. Select a folder or ZIP destination and generate it.
5. Open the destination's `wayricad/<run-id>/index.html`. A durable copy also remains in the project's `reports/wayricad/<run-id>/` folder, including on failure.

To add the sequence to an existing jobset without replacing it:

```text
wayricad-jobs jobset --config wayricad-jobs.json --merge fabrication.kicad_jobset --position 2 --output fabrication-with-reports.kicad_jobset
```

Positions are zero-based; omit `--position` to append. Existing jobs, settings and destinations are preserved. The report job is inserted into every destination, including destinations with explicit job-selection lists. Review that choice in KiCad before running. Use separate configurations/jobs when different destinations require different analyses.

Generated jobsets use the current Python executable directly, so its Scripts folder does not need to be on `PATH`. Install the wheel in that interpreter first. To use another environment, select `--python`, or supply `--runner` with the full `wayricad-jobs` executable path. Example on Windows:

```text
wayricad-jobs jobset --config wayricad-jobs.json --python "C:/Tools/WayriCAD/python.exe" --output WayriCAD.kicad_jobset
```

Generated jobsets reference the selected project/configuration paths and platform shell. Regenerate after moving the project or changing machines; use `--platform windows` or `--platform posix` when generating for a different host. Windows command paths containing `%`, `!`, or double quotes are rejected because `cmd.exe` expands them. Step commands themselves run as argument arrays with `shell=False`.

KiCad collects job outputs through `JOBSET_OUTPUT_WORK_PATH`. The runner copies the complete report folder there after each sequence and retains its project-local copy. Native jobsets may discard failed temporary outputs; the local copy prevents losing the diagnostics. See [KiCad's official jobset documentation](https://docs.kicad.org/10.0/en/kicad/kicad.html#jobsets).

## Presets

Run `wayricad-jobs presets` for the installed catalog.

| Preset | Reports | Inputs and limits |
|---|---|---|
| `fabrication` | Native DRC JSON, ERC JSON, BOM CSV and board-statistics JSON | Saved project, board and schematic; KiCad CLI. DRC/ERC errors or warnings fail their steps. BOM requires successful ERC; statistics requires successful DRC. |
| `inventory` | RLC, Quick PI and Quick SI inventory JSON | Saved board and prepared native runtimes. Lists available analysis inputs; no selected-path solve. |
| `electrical` | PI JSON/HTML, SI JSON/HTML and RLC JSON | Explicit net, pads, voltage, current, rise time and frequency. Each tool retains its own coverage and approximation limits. |
| `bom` | Existing BOM Studio pipeline exports, reports and checked manifest | Explicit BOM pipeline configuration; retains its templates, conditional exports and policy gates. |

Configure an electrical path without baking demo values into the preset:

```text
wayricad-jobs init Example.kicad_pro --preset electrical --output electrical-jobs.json --set net=VCC --set source=J1.1 --set sink=U1.1 --set voltage=3.3 --set current=1 --set rise_ns=1 --set frequency_mhz=100
```

These example values must be replaced with your actual design assumptions. Power rails and signal nets often need **different configurations**. The electrical preset is a convenient sequence, not a claim that all three models suit every net. Edit the PI argument list to use its existing `--command` series-R/RL syntax or add `--converge-levels 4`; use the SI `suite` command in a later step to aggregate protocol reports. RLC supports `path` and `zone`, frequency sweeps, and its documented limitations.

For BOM Studio:

```text
wayricad-jobs init Example.kicad_pro --preset bom --output bom-jobs.json --set bom_pipeline=bom-pipeline.json
```

Use a reviewed BOM Studio pipeline (for example, `bom_studio_plugin/examples/automation/pipeline-default.json`). Relative arguments resolve from the project directory. The runner gives BOM Studio a fresh `bom/` directory; it does not bypass the existing export or policy checks.

## Customize a sequence

Configuration schema: `wayricad.jobs/v1`. Steps execute in list order. IDs are unique simple names; `depends_on` may only reference earlier steps. The following produces an offline SI protocol summary after reports from prior steps:

```json
{
  "id": "protocol_summary",
  "label": "Protocol review",
  "argv": ["${python}", "-m", "signal_integrity_advisor_plugin.cli", "suite",
           "--profile", "${protocol}", "--reports", "${output}/lane_p/si.json", "${output}/lane_n/si.json",
           "--output", "${step_dir}/protocol.json", "--html", "${step_dir}/protocol.html"],
  "outputs": ["protocol.json", "protocol.html"],
  "depends_on": ["lane_p", "lane_n"],
  "timeout_seconds": 180
}
```

Define `protocol` in the top-level `variables` object using a profile ID from `wayricad-si profiles`. Supply matching prior step IDs. Protocol screening is not compliance certification.

Available placeholders: `${project}`, `${project_dir}`, `${board}`, `${schematic}`, `${output}` (this run), `${step_dir}`, `${python}`, `${native_python}`, `${kicad_cli}`, and your top-level `variables`. Expansion is literal, not shell evaluation. Arguments are separate JSON strings, so spaces in paths and net names are preserved. Required `outputs` are nonempty files relative to the current step directory; `../` traversal is rejected.

Any existing CLI can be an explicit custom step: pin/ICD reports from exported netlists, mechanical reports, routing **plan** JSON/SVG, or magnetics calculations from a reviewed specification. Configure its required runtime and report files. GUI-only tools are not automatically made headless; Manufacturing Readiness and Constraint Studio currently have no production report CLI. Custom commands are executable code: use configurations you understand. Mutating routing `apply`, library repair, and source edits are deliberately absent from supplied report presets.

## Failure and concurrency behavior

- Default: stop after the first failed step. `--keep-going` runs independent remaining steps; dependent steps stay skipped. Any failed or skipped step makes the overall run fail.
- Default per-step timeout: 300 seconds, configurable up to 86400. Timeout or cancellation terminates the child process; process-tree termination is attempted on supported hosts. Logs remain available.
- A command returning zero without its required report files fails. Old files cannot satisfy a new run because every run gets a fresh directory.
- Saved project, board, schematic sheets, rules and configuration are hashed before and after execution. Changes invalidate the run. This detects edits; it is not a locked snapshot or rollback system. Save before running and avoid editing during a release sequence.
- Concurrent runs and multiple KiCad instances use separate run folders. `latest.html` points to the last completed run; each complete history remains available.
- Exit codes: `0` sequence passed, `1` failed/partial sequence, `2` invalid configuration/runtime setup, `130` cancelled. Native subprocess exit codes are retained in `summary.json`.
- `run --dry-run` and `validate` display expanded commands without executing analyses or creating report folders. They do not establish that every optional runtime/model is installed.

Set `KICAD_CLI` when KiCad is outside normal install locations. Set `WAYRICAD_KICAD_PYTHON` when native Python discovery needs an override. Prepare PI/native dependencies before an unattended job; first-time runtime installation may require network access. HTML reports are local and need no CDN.

## Validation evidence

The report runner is tested for ordering, dependencies, failure exits, timeouts, missing outputs, changed inputs, literal arguments, concurrent-safe run directories, native output collection and HTML escaping. Native KiCad 10 on Windows was exercised with a three-job sequence, a real PCB statistics export, paths containing spaces, and a deliberate failed job. Other platform shell execution and unsaved editor-state capture are not certified by that check.
