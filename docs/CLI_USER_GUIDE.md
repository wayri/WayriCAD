# KiWay CLI User Guide

The KiWay CLI extracts electrical interface data without opening the plugin
windows. Use it for repeatable ICD generation, design validation, cross-board
linking, continuous integration, and KiCad jobset output pipelines.

## 1. Installation and runtime selection

Install the repository into a normal Python 3.9 or newer environment:

```bash
python -m pip install -e .
kiway --version
kiway dependencies
```

Use `python -m extract_pins_plugin` wherever the `kiway` launcher is not on
`PATH`. XML netlist, report, cross-link, validation, and inspection commands do
not import `pcbnew`. `board-extract` and `board-list` do require a Python runtime
that can import the KiCad `pcbnew` module.

On Windows, a board command can be launched explicitly with KiCad's Python:

```powershell
& 'C:\Program Files\KiCad\10.0\bin\python.exe' -m extract_pins_plugin `
  board-extract .\controller.kicad_pcb --refs 'J*' --format csv `
  --output .\artifacts\connector-pins.csv
```

Run `kiway COMMAND --help` for command-specific options. Global options such as
`--config`, `--diagnostics`, and `--quiet` must appear before the command.

## 2. Inputs and deterministic outputs

Schematic commands accept KiCad XML netlists, `.net` files, or directories. A
directory is searched recursively and all matching inputs are processed in
sorted order. Export a compatible netlist with KiCad 10 using:

```bash
kicad-cli sch export netlist --format kicadxml \
  --output artifacts/controller.xml controller.kicad_sch
```

Use `--format json` for automation, `csv` for spreadsheet/database import,
`md` or `html` for review documents, and `svg` for diagrams. Use `--output` to
write a file; otherwise output is written to stdout. Parent output directories
are created automatically.

## 3. Project inspection

Inspect parsed components, sheets, interfaces, and optional pin rows before
building a report:

```bash
kiway inspect exports/ --include-pins \
  --board-sequence DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO \
  --sheet-alias 'ADCS IMU:/Main/ADCS/*:U*' \
  --format json --output artifacts/project-inventory.json
```

`--sheet-alias` has the form `Name:path_glob:reference_glob` and can be repeated.
Native hierarchical sheet paths are preserved even when a friendly alias is
applied.

## 4. Electrical data extraction

The `extract` command supports six datasets:

| Kind | Purpose |
|---|---|
| `pins` | Component, sheet, pin function, net, board endpoint, and TM/TC data |
| `connectors` | Connector-oriented ICD rows |
| `testpoints` | Test-point net and resolved function rows |
| `tm-tc` | `TM`, `TA`, `TD`, `TC`, `CA`, and `CD` signal records |
| `interfaces` | Consolidated buses, differential pairs, and logical interfaces |
| `controller-map` | Auditable controller/IC-to-connector paths across exact approved pin pairs |

Examples:

```bash
kiway extract exports/controller.xml --kind connectors --format csv \
  --output artifacts/connectors.csv

kiway extract exports/ --kind tm-tc --consolidate \
  --board-sequence DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO --format csv \
  --output artifacts/tm-tc.csv

kiway extract exports/ --kind interfaces --format svg \
  --output artifacts/interfaces.svg

kiway extract exports/controller.xml --kind controller-map \
  --source-refs U1,U2 --connector-refs J* \
  --path-rule "Q12 | D-S | active | verify MOSFET state" \
  --path-rule "Q20 | C-E | active | verify BJT bias" \
  --include-active-paths --format csv \
  --output artifacts/controller-connector-map.csv
```

Board endpoint order is inferred from the order of tokens in
`--board-sequence`, not from one rigid label template. TM/TC identifiers are
recognized as underscore-delimited tokens.

Controller-map safe defaults cross only two-terminal series resistors,
inductors, ferrites, and fuses. Capacitors are excluded because they are
normally shunts. MOSFET, BJT, jumper-state, and other IC routes require an exact
pin-pair rule plus `--include-active-paths`; these rows are marked
`Conditional`. Pin tokens may be physical numbers or XML netlist pin functions.
Use `--path-rules-file` for reviewed team rules, `--exclude-ambiguous` for a
strict publication artifact, and `--max-hops`/`--max-paths` as traversal bounds.
Source and connector indicate reporting scope only; KiWay does not infer
semiconductor state or electrical direction.

## 5. Cross-project and harness linking

`crosslink` imports KiWay CSV or Markdown pin documents. It first applies exact
and normalized net matching, then any supplied wildcard or regular-expression
rules. Power links are excluded unless `--include-power` is present.

```bash
kiway crosslink demo_ctrl-pins.csv demo_sensor-pins.md \
  --project DEMO_CTRL --project DEMO_SENSOR \
  --rules-file docs/examples/crosslink.rules.txt \
  --format json --output artifacts/cross-links.json

kiway crosslink demo_ctrl-pins.csv demo_sensor-pins.md \
  --project DEMO_CTRL --project DEMO_SENSOR \
  --rules 'Board prefix | wildcard | DEMO_CTRL_* | DEMO_SENSOR_*' \
  --format svg --output artifacts/harness.svg
```

Keep rule files under version control. Review ambiguous one-to-many links before
using the result as a harness definition.

## 6. Validation and CI gates

`validate` emits deterministic diagnostics and returns exit code `3` when a
required rule fails:

```bash
kiway --diagnostics json validate exports/ \
  --board-sequence DEMO_CTRL,DEMO_SENSOR \
  --require-tm-consumer --require-tc-origin \
  --format json --output artifacts/kiway-validation.json
```

Useful pipeline stages are:

1. Export `kicadxml` from the schematic with `kicad-cli`.
2. Run KiCad ERC and PCB DRC.
3. Run `kiway validate` as an interface-contract gate.
4. Generate the ICD and machine-readable pin tables.
5. Publish the entire artifact directory.

GitHub Actions example:

```yaml
- name: Install KiWay
  run: python -m pip install -e .
- name: Export KiCad netlist
  run: kicad-cli sch export netlist --format kicadxml --output artifacts/design.xml design.kicad_sch
- name: Validate interfaces
  run: kiway --diagnostics json validate artifacts/design.xml --board-sequence DEMO_CTRL,DEMO_SENSOR --require-tm-consumer --require-tc-origin --format json --output artifacts/validation.json
- name: Build ICD
  run: kiway report artifacts/design.xml --board-sequence DEMO_CTRL,DEMO_SENSOR --format html --output artifacts/electrical-icd.html
```

The same commands work in GitLab CI, Jenkins, Azure Pipelines, Make, Ninja, or a
PowerShell build script. Avoid shell redirection for structured output; use
`--output` so failures and diagnostics remain separate from the generated file.

## 7. Configuration files

Pass `--config` before the command. The JSON object can contain shared
`defaults` and command-specific keys. Explicit non-empty CLI values win.

```bash
kiway --config docs/examples/kiway.config.json extract exports/ \
  --kind tm-tc --output artifacts/tm-tc.csv
```

Option names use underscores in JSON, for example `board_sequence`,
`sheet_alias`, `include_power`, and `consolidate`.

## 8. KiCad jobset integration

KiCad 9 and later can run `.kicad_jobset` files in the Project Manager or with
`kicad-cli`. KiWay supports two integration patterns.

### Run a native jobset through KiWay

```bash
kiway jobset-run controller.kicad_pro --file release.kicad_jobset \
  --stop-on-error

kiway jobset-run controller.kicad_pro --file release.kicad_jobset \
  --destination Manufacturing

kiway jobset-run controller.kicad_pro --file release.kicad_jobset \
  --dry-run
```

The destination may be its unique description or ID. `jobset-run` uses the
native `kicad-cli jobset run` implementation; it does not rewrite the jobset.
Executable discovery order is `--kicad-cli`, `KICAD_CLI`, `PATH`, then standard
KiCad 10/9 installation locations.

### Add KiWay as an Execute Command job

In the KiCad Jobset editor:

1. Add a **Schematic: Export Netlist** job using `kicadxml` format. Name its
   output `electrical.xml`.
2. Add a **Special: Execute Command** job after the netlist job.
3. Configure non-zero exit codes to fail the job.
4. Use this command:

```text
kiway report "${JOBSET_OUTPUT_WORK_PATH}/electrical.xml" --board-sequence DEMO_CTRL,DEMO_SENSOR --format html --output "${JOBSET_OUTPUT_WORK_PATH}/electrical-icd.html"
```

Add another Execute Command job for validation:

```text
kiway --diagnostics json validate "${JOBSET_OUTPUT_WORK_PATH}/electrical.xml" --board-sequence DEMO_CTRL,DEMO_SENSOR --require-tm-consumer --require-tc-origin --format json --output "${JOBSET_OUTPUT_WORK_PATH}/interface-validation.json"
```

KiCad generates destination files in a temporary work directory before moving
them into the final folder or archive. Therefore, Execute Command jobs must use
`${JOBSET_OUTPUT_WORK_PATH}` when reading an earlier job's output or creating a
file that must be included in the destination. Job ordering matters.

For reproducible team use:

- Commit the `.kicad_jobset`, KiWay config, and cross-link rules together.
- Use paths relative to the project or jobset work directory.
- Pin the KiWay revision in CI.
- Ensure `kiway` is on the environment inherited by KiCad. If it is not, use an
  absolute virtual-environment launcher or `python -m extract_pins_plugin`.
- Do not edit `.kicad_jobset` JSON by hand; configure and save it with KiCad.

The native command equivalent is:

```bash
kicad-cli jobset run --stop-on-error --file release.kicad_jobset controller.kicad_pro
```

See the [KiCad 10 CLI jobset documentation](https://docs.kicad.org/10.0/en/cli/cli.html#jobset-commands)
for native destination behavior and options.

## 9. Reports and documentation bundles

Create one complete interface control document:

```bash
kiway report exports/ --title 'DEMO_CTRL Electrical ICD' \
  --board-sequence DEMO_CTRL,DEMO_SENSOR,DEMO_POWER,DEMO_IO \
  --imports demo_ctrl-pins.csv demo_sensor-pins.csv \
  --rules-file docs/examples/crosslink.rules.txt \
  --format html --output artifacts/demo_ctrl-icd.html
```

`report` supports Markdown, HTML, CSV, JSON, and SVG. CSV report output contains
the TM/TC table; use individual `extract` commands when separate connector,
test-point, pin, and interface CSV files are required.

## 10. Exit codes and diagnostics

| Code | Meaning |
|---:|---|
| `0` | Command completed successfully |
| `1` | Runtime, dependency, or native jobset execution failure |
| `2` | Invalid arguments, missing input, or unavailable executable |
| `3` | Validation completed and found a gating error |

Diagnostics go to stderr. `--diagnostics json` is recommended for CI log
collectors. `--quiet` suppresses non-error diagnostics but never hides errors.

## 11. Troubleshooting and limitations

- **No XML inputs found:** export a `kicadxml` netlist; a `.kicad_sch` file is
  not itself a CLI parser input.
- **`pcbnew` unavailable:** use KiCad's bundled Python for board commands.
- **`kicad-cli` not found:** set `KICAD_CLI` or pass `--kicad-cli`.
- **Jobset command works in a terminal but not KiCad:** use an absolute launcher
  path because the GUI may inherit a different `PATH`.
- **Jobset report is absent from an archive:** write it under
  `${JOBSET_OUTPUT_WORK_PATH}` and place the Execute Command job before the
  destination is finalized.
- **Unexpected links:** disable exact or normalized matching and use explicit
  reviewed rules; power links are opt-in.
- **Board output differs from schematic output:** board commands inspect the
  saved `.kicad_pcb`; save the editor state before automation.

KiWay's first-order electrical estimates and inferred interface direction are
review aids. They do not replace ERC/DRC, a field solver, TDR measurement, or an
approved interface-control review.
