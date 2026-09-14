# WayriCAD BOM Studio 0.8.2 — Command-line reference

The v0.8.1 contracts below override earlier examples that omit an explicit custom export/release template. 37 command families are available; saved native data remains distinct from pending workspace edits.

```powershell
# Read current native inheritance and definitions.
py -3 .\cli.py bom-format show Board.kicad_pro --output format-context.json
# Explicit mode changes preserve existing component edits and custom definitions.
py -3 .\cli.py bom-format follow Board.kicad_pro
py -3 .\cli.py bom-format customize Board.kicad_pro --template "My BOM"
py -3 .\cli.py bom-format merge Board.kicad_pro --template "My BOM"
py -3 .\cli.py bom-format use-custom Board.kicad_pro --template "My BOM"
# Review reverse settings, then stage only; no native write here.
py -3 .\cli.py bom-format preview Board.kicad_pro --template "My BOM" --output format-plan.json
py -3 .\cli.py bom-format apply Board.kicad_pro --plan format-plan.json --confirm FORMAT --acknowledge-replacement
# Separate native file write still requires closed editors and its own plan/APPLY.
py -3 .\cli.py native preview Board.kicad_pro --output native-plan.json
py -3 .\cli.py native apply Board.kicad_pro --plan native-plan.json --confirm APPLY --editors-closed
# Native and enhanced outputs are deliberately distinct.
py -3 .\cli.py native-bom Board.kicad_pro --acknowledge-saved-only --output native.csv
py -3 .\cli.py export Board.kicad_pro --format csv --acknowledge-saved-only --output native-equivalent.csv
py -3 .\cli.py export Board.kicad_pro --template "My BOM" --format xlsx --output custom.xlsx
py -3 .\cli.py release Board.kicad_pro --template "My BOM" --output variants.zip
```

`bom-format follow` accepts --preset and --format-preset IDs reported by show; @current means the saved active settings. All output files must be new. Mutating bom-format commands refuse --source-only. Native CSV is produced by installed KiCad; no native executable means a capability error, not another engine's output. No hidden browser or native-write action is added to headless commands. Existing pipeline templates remain explicit in JSON.

---

# WayriCAD BOM Studio 0.8.1 — CLI additions and installed layout

Run commands from the installed `org_wayricad_bomstudio` folder, or from `plugins` after extracting a copy for standalone use. Use `python cli.py` (Windows `py -3 .\cli.py`), not an extra `wayricad_bom_studio/` wrapper. Use the intended interpreter. The current package has **36 command families**. Earlier examples below retain their original feature semantics; this section supersedes version/launcher details.

```powershell
# Exact fields, blanks, display labels and native presets; read-only.
py -3 .\cli.py fields "C:\Projects\Board\Board.kicad_pro" --output ".\field-audit.json"

# Native saved-source BOM, explicitly separate from pending WayriCAD changes.
py -3 .\cli.py native-bom "C:\Projects\Board\Board.kicad_pro" --acknowledge-saved-only --output ".\native-bom.csv"

# Finder with category/manufacturer/asset filters before paging.
py -3 .\cli.py catalog search --library "C:\Parts\Catalogue" --category "Passives/Resistors" --sort mpn --summary

# New native library; edit new-library.json first. Preview does not create the destination.
py -3 .\cli.py library-create preview --request ".\new-library.json" --output ".\library-plan.json"
# Read the complete review and warnings before confirming.
py -3 .\cli.py library-create apply --plan ".\library-plan.json" --confirm CREATE --output ".\creation-receipt.json"

# Embedded is the default; browser is deliberate troubleshooting only.
py -3 .\cli.py gui "C:\Projects\Board\Board.kicad_pro" --ui desktop
py -3 .\cli.py gui "C:\Projects\Board\Board.kicad_pro" --ui browser
```

`fields` accepts active variant and `--source-only`. `native-bom --config FILE` accepts data-only options (`preset`, `format_preset`, `fields`, `labels`, `group_by`, `sort_field`, `sort_asc`, `filter`, population/formatting flags). The installed command's help is checked; unavailable native CLI exits 6. Native output is not transformed or spreadsheet-formula escaped by WayriCAD. BOM-only variants/pending edits are not silently written.

`library-create` inputs are JSON; `-` accepts stdin. Empty example:

```json
{"mode":"empty","destination":"C:/Users/You/Documents/NewParts","name":"NewParts","actor":"Your name","require_complete":true}
```

For projects, set `mode:"projects"` and add `projects:["C:/Projects/Board/Board.kicad_pro"]`. A new catalogue is created automatically. Optional `recursive`, `all_variants`, `asset_options`, `allow_partial_projects`, and strict `require_complete` are described in V8_WORKFLOWS. Existing-catalogue mode needs `library` and `ids` or an explicit `all_parts:true`. `choices` maps part IDs to captured set IDs. Existing destinations are refused. No `--overwrite` exists. Apply rechecks sources/revisions and the reviewed native bytes. This CLI writes the new directory only; GUI attach/remember are not implicit CLI actions. Native table registration remains explicit in KiCad.

Additional `catalog search` options: `--category` (includes descendants), `--manufacturer` (stored exact facet), `--lifecycle RISK|RECORDED|UNKNOWN`, `--sort mpn|manufacturer|value|category|internal_pn|updated|status|revision`, `--descending`, `--summary`. These combine with prior `--query`, `--filters`, `--has-asset`, status and pagination. The API's `records_loaded` is the actual returned page count.

---

> **v0.7.1 PCM layout:** execute `python cli.py ...` from the installed `org_wayricad_bomstudio` directory, or `python plugins/cli.py ...` from an extracted PCM archive. The older outer `wayricad_bom_studio` path in examples belongs to manual bundles. Current installation: `PCM_INSTALL.md`. Command behavior is unchanged.

# WayriCAD BOM Studio 0.7 — Command-line reference

See the version 0.8.2 section at the end for `vendors` and supplier upload pipelines. 38 current command families; earlier versioned sections describe retained capabilities.

## Entry points and contract

Python 3.10+ is required. From the distribution folder, use `python wayricad_bom_studio/cli.py ...`; on Windows, `py -3 .\wayricad_bom_studio\cli.py ...` selects the Python Launcher. From the plugin folder, `python -m bomstudio ...` is equivalent. `python cli.py --help`, `python cli.py COMMAND --help`, and preview/apply subcommand help describe exact options. Option abbreviations are disabled. Help/version are text; headless results are JSON.

This reference uses `python cli.py` while in the plugin folder and a saved `Board.kicad_pro`. Replace that project path with your own. Output parent directories must already exist, and named output files/run directories must **not** exist. There is deliberately no overwrite switch.

By default the CLI loads native files and a saved `.wayricad-bom.json`. Read-only project commands accept `--source-only` to ignore the sidecar. A browser's unreviewed grid edits and unsaved workspace changes are not included. Do not operate on the same saved workspace from multiple writers without coordinating and reloading them. File checks cannot detect unsaved KiCad editor memory.

Successful command results and policy findings use a `wayricad-cli-1` envelope on stdout:

```json
{"schema":"wayricad-cli-1","version":"0.6.0","command":"query","ok":true,"data":{}}
```

Input/operational failures use `wayricad-cli-error-1` on stderr. With `--output report.json`, the file contains the raw report or plan; stdout carries a receipt with path, size and hash. Read commands with no output file print the envelope only. Data-only JSON inputs accept a filename or `-` for stdin; inputs may also be a result envelope with the actual data nested under `data`. Duplicate keys, unsafe prototype keys, nonfinite values and oversized inputs are rejected. `--debug` before the command adds internal tracebacks on unexpected failures and may expose local paths. Foreground `gui` prints its private session URL rather than a headless JSON stream.

| Exit | Meaning |
|---|---|
| 0 | Command completed; inspect report semantics as well |
| 2 | Invalid input, arguments, recipe or unsupported option |
| 3 | Validation/release policy failure, or integrity verification failure |
| 4 | File/output/permission problem |
| 5 | Stale review, changed source, or required confirmation missing |
| 6 | Required optional capability unavailable |
| 7 | Unexpected internal failure |
| 130 | Interrupted |

A valid hash report may describe a **FAILED** pipeline. Treat `verify` success as integrity, never manufacturing approval. Plans can contain values and absolute paths; store them as sensitive project data. Preview fingerprints detect drift; they are not digital signatures or authenticated approvals.

## 23 retained command families

Ten additional engineering command families are documented in the version 0.6 section below (33 total).

| Command | Purpose and key options |
|---|---|
| `doctor` | Python/platform, local `kicad-cli`, optional SDK and inherited IPC diagnostics; no project needed |
| `info PROJECT` | Project, variant, source hashes and saved-workspace summary |
| `list PROJECT` | `--what variants|templates|fields|filters|profiles|variables` |
| `query PROJECT` | `--query`, `--filter`, `--case-sensitive`, `--rows`, repeated `--group-by`, `--limit`, `--offset` |
| `analytics PROJECT` | Mapped price/mass/dissipation, budgets, statistics, scenarios and report exports; `--config`, explicit flags, `--format`, `--table`, `--fail-on` |
| `threshold PROJECT` | `--field`, `--condition`, `--unit`, optional query/rows, `--fail-on-match`, `--fail-on-unknown` |
| `check PROJECT` | BOM-data checks; `--fail-on none|error|warning|unknown`, default error |
| `health PROJECT` | Existing footprint/evidence/stock screening; same fail-on values, default none |
| `analyze PROJECT` | Consolidation and equivalent-value assessment; advisory, no substitutions |
| `export PROJECT` | `--template`, `--format`, required `--output`, explicit `--draft` |
| `release PROJECT` | Existing all-variant ZIP; optional `--variants`, template, output and explicit draft |
| `compare PROJECT` | `--left` and required `--right` variant names |
| `bulk preview/apply PROJECT` | Query/ID-scoped ordered field and population actions |
| `config preview/apply PROJECT` | Reviewed variables, variants, settings, aliases and template/filter changes |
| `native preview/apply PROJECT` | Separate backed-up native-file synchronization |
| `enforce preview/apply PROJECT` | Project-wide field profile enforcement |
| `evidence preview/apply PROJECT` | Reviewed supplier/package evidence import |
| `templates PROJECT` | Portable template bundle, optional `--section` and `--name` |
| `run PROJECT` | Data-only release pipeline with policy gates |
| `jobset PROJECT` | Native job-set and runner generator, directory or ZIP |
| `verify DIRECTORY` | Pipeline manifest/path/hash/size verification |
| `gui [PROJECT]` | Foreground GUI, optional explicit detached launch |
| `schema` | JSON contract identifiers, commands, exit codes and default pipeline |

Commands that operate on a single variant accept `--variant`; the default/base identifier is `<Default>`. Use `list --what variants` rather than guessing a display name. `release`, `run`, native/profile/config/evidence operations and bundle operations have their documented multi-variant/project scope. A subset of configuration operations is exposed; the CLI is not an unrestricted mirror of every internal HTTP endpoint.

## Inspection, search and exports

```sh
python cli.py doctor
python cli.py info Board.kicad_pro
python cli.py list Board.kicad_pro --what fields
python cli.py query Board.kicad_pro --query 'Reference~"R*" AND Value=10k' --rows
python cli.py query Board.kicad_pro --query 'is:fit AND missing:MPN' --output missing-mpn.json
python cli.py query Board.kicad_pro --filter "Production resistors" --group-by Value --group-by Footprint
python cli.py check Board.kicad_pro --fail-on warning --output checks.json
python cli.py health Board.kicad_pro --fail-on unknown --output health.json
python cli.py analyze Board.kicad_pro --output consolidation.json
python cli.py compare Board.kicad_pro --left "<Default>" --right Economy --output changes.json
python cli.py export Board.kicad_pro --variant Economy --template Purchasing --format xlsx --output Economy.xlsx
python cli.py release Board.kicad_pro --template Purchasing --output all-variants.zip
```

These examples use POSIX/PowerShell-style single-quoted queries. In Windows `cmd.exe`, escape/quote according to that shell or use saved-filter names to avoid complex argument quoting. Supported single-export format keys: `csv`, `tsv`, `xlsx`, `ods`, `txt`, `asc`, `xml`, `json`, `jsonl`, `md`, `html`. ZIP is `release`. Generic XML is not IPC-2581/ODB++/a native XML netlist. Draft output is explicitly labeled and does not represent a policy-cleared release.

Query syntax, operator precedence, raw/resolved values and bounded parsing are in `V4_WORKFLOWS.md`. `--group-by` can be repeated; it groups the matched rows without changing the saved view or merging procurement identities. Pagination reports `next_offset` and, for grouping, `next_group_offset`. Query rows are physical components; grouping results are a separate array. Health findings are not automatically exposed as `is:error`; that predicate uses BOM-data checks.

## Reviewed bulk edits

`examples/automation/bulk-standardize-value.json` demonstrates an explicit scope. Minimal recipe:

```json
{
  "schema":"wayricad-bulk-recipe-1",
  "query":"Reference~\"R*\" AND Value=10k",
  "operations":[
    {"op":"set","field":"ReviewNote","value":"  review requested  "},
    {"op":"trim","field":"ReviewNote"},
    {"op":"upper","field":"ReviewNote"}
  ]
}
```

```sh
python cli.py bulk preview Board.kicad_pro --recipe bulk.json --output bulk-plan.json
# Read the complete plan. It has not changed the workspace or KiCad files.
python cli.py bulk apply Board.kicad_pro --plan bulk-plan.json --confirm EDIT
```

Provide the same `--variant` at preview and apply for a named-variant plan. Add `--acknowledge-loss` only after reviewing an identified expression-loss warning. Apply writes the sidecar, not native files. It is one Undo in a live GUI transaction, but CLI processes do not provide a persistent undo stack; use sidecar backups/version control and reload any open GUI after a CLI write.

Recipes can use `ids` instead of `query`. Empty-query all-parts scope requires `allow_all:true`. Accepted operations and data keys:

| Operation | Extra keys | Semantics |
|---|---|---|
| `set` / `fill_empty` | `value` | Replace / fill only a blank value |
| `clear` | none | Blank a field; no property deletion |
| `trim` / `upper` / `lower` | none | Literal text transformation |
| `prefix` / `suffix` | `value` | Add literal text |
| `replace` | `find`, `value` | Literal nonempty find text, no regex |
| `copy` | `source` | Copy source raw expression/value |
| `reset_to_base` | none | Reset the field's override |

Every operation has `field`. Set/FIT/DNP/DNI and boolean flags use the existing native-compatible field mapping; generated fields and reserved identities remain protected. Reset followed by a text transform/copy of the reset value is rejected—split the recipe so inherited resolution is reviewed between steps. A later explicit set can supersede reset. Operations across aliases of the same physical property retain their intended order.

## Configuration, templates and evidence

Configuration input is a JSON array. Example:

```json
[
  {"op":"variant-add","name":"Prototype","parent":"<Default>","description":"Review build"},
  {"op":"filter-save","name":"Production resistors","record":{"query":"Reference~\"R*\" AND is:fit","case_sensitive":false,"description":"Fitted resistor references"}}
]
```

```sh
python cli.py config preview Board.kicad_pro --changes config.json --output config-plan.json
python cli.py config apply Board.kicad_pro --plan config-plan.json --confirm CONFIG
python cli.py templates Board.kicad_pro --output team-templates.json
python cli.py enforce preview Board.kicad_pro --profile "Engineering standard" --output field-plan.json
python cli.py enforce apply Board.kicad_pro --plan field-plan.json --confirm ENFORCE
python cli.py evidence preview Board.kicad_pro --payload evidence-payload.json --output evidence-plan.json
python cli.py evidence apply Board.kicad_pro --plan evidence-plan.json --confirm IMPORT --reviewed
```

Allowed config ops: `variant-add` (name,parent,description), `variant-remove` (name), `variables` (scope,values,optional variant), `settings` (settings object), `aliases` (aliases object), `analytics-settings` (validated `settings` object), `template-save` (template object), `profile-save` (profile object), `template-import` (bundle object, policy `keep_both|replace|skip`), `filter-save` (name,record), `filter-remove` (name). Existing schema validation applies. Scope variable updates replace that scope's submitted dictionary, not one unnamed key; inspect the full diff. Variable changes and destructive config operations require `--acknowledge-loss`. Native variant deletion/rename remains KiCad's responsibility.

Enforcement `--options` accepts the documented data-only v0.2 option object. The evidence payload is the existing import payload (for example `{"format":"manual","record":{...}}`), not a guessed raw distributor API response. Export/import templates never automatically enforce them. Evidence imports do not substitute parts or silently change cost assumptions.

## Separate native synchronization

```sh
python cli.py native preview Board.kicad_pro --output native-plan.json
# Inspect diff and backups policy. Close every KiCad editor for this project.
python cli.py native apply Board.kicad_pro --plan native-plan.json --confirm APPLY --editors-closed
```

Native apply refuses stale plans and supported lock/source conditions, writes original-file backups and validates with WayriCAD's parser/adapter. That is not a real KiCad reload or an ERC/DRC check. Multi-file writes are recoverable but not atomic against power loss. Reopen and inspect in KiCad, then Update PCB from Schematic separately. There is no automatic native apply in a pipeline or generated job set.

## Release pipelines

Start with `examples/automation/pipeline-default.json` or the GUI pipeline editor:

```json
{
  "schema":"wayricad-pipeline-1",
  "name":"WayriCAD_BOM",
  "variants":"all",
  "template":"Purchasing",
  "formats":["csv","xlsx","json","txt"],
  "reports":["checks","health","analysis"],
  "policy":{"checks":"error","health":"none","require_stock":false}
}
```

```sh
python cli.py run Board.kicad_pro --config pipeline.json --output-dir release-001
python cli.py verify release-001
```

`variants` can instead be an array of 1–100 unique names. Checks always run, even if omitted from `reports`. `policy.checks` accepts `error` or `warning`; it cannot be disabled. `policy.health` accepts `none`, `error`, `warning`, `unknown`. `require_stock:true` requires each fitted exact manufacturer/MPN demand to have an eligible reviewed observed offer covering order demand. Invalid/stale/unscoped evidence is not accepted as stock; no live requests are made. A strict policy can generate many failures on a project without complete evidence.

A passing run publishes numbered per-variant folders to avoid filename collisions. A failing gate still publishes reports and a FAILED manifest, but no BOM exports. Source changes abort publishing. The manifest contains config, source/workspace hashes, timestamp, variant directory mapping, status, gates and per-file size/hashes. The full `workspace_snapshot.json` may contain proprietary fields, absolute paths and evidence. Hashes do not confer signatures, trusted authorship, electrical qualification or approval. Native ERC/DRC and additional manufacturing outputs belong in separate KiCad jobs.

## Job-set generation and GUI launch

```sh
python cli.py jobset Board.kicad_pro --directory /absolute/path/new-jobs --config pipeline.json
python cli.py jobset Board.kicad_pro --directory /absolute/intended/extraction --zip new-job-bundle.zip
kicad-cli jobset run --file /absolute/path/new-jobs/WayriCAD_BOM.kicad_jobset --stop-on-error Board.kicad_pro
```

`--directory` must be absolute and, without `--zip`, not exist. `--python` selects an exact interpreter. `--platform windows|posix` chooses shell quoting; generate on the target machine so its paths are real. The supplied runner is code you can inspect; imported pipeline configuration cannot insert arbitrary commands. Native job sets themselves contain shell commands, so treat unknown job-set bundles as executable and review them.

Inside a native Execute Command job, `run ... --jobset-output` uses only an existing absolute `JOBSET_OUTPUT_WORK_PATH` supplied by KiCad. Calling it without that environment fails explicitly. The generated runner detects that environment; outside it, the runner creates a unique manual-run directory. Output destination copying after a failed job is controlled by KiCad, not WayriCAD.

```sh
python cli.py gui Board.kicad_pro
python cli.py gui Board.kicad_pro --detach
python cli.py gui --demo --no-auto-link
```

A foreground GUI blocks until Quit. Detached launch returns a session receipt with PID/private URL/log directory; use only for a deliberately interactive task. Disable native job-set output recording for a GUI-launch job to avoid logging the session URL. No request from the assistant is scheduled by these commands; they execute when the user runs them. CLI `doctor` diagnoses the optional IPC environment; live linking itself is driven from the GUI, not a persistent cross-highlight CLI service.

## Compatibility and recovery

The original positional syntax `python -m bomstudio PROJECT --format xlsx --output ...` still works and prints a migration warning. New scripts should use subcommands and JSON/exit codes. Apply commands are not idempotent approvals; preview again after a successful mutation or any source change. Existing native-file compatibility gates and variable restrictions remain in force. `schema` is a compact contract discovery report, not a complete external JSON-Schema validator.

The automated suite exercises parsers, safety, all export modes, reviewed transactions, pipelines, output collisions, integrity, job runner environment and CLI failures. Host job-set execution, Windows/macOS shell launch and native KiCad relay/focus remain untested. See `TEST_REPORT.md` and `V4_WORKFLOWS.md`.


## Cost, mass, thermal-dissipation and numeric analytics (0.5)

`analytics` is distinct from `analyze`: **analytics** performs quantitative user-data calculations; **analyze** is the earlier consolidation/equivalent-value assessment. Read `V5_WORKFLOWS.md` for population, uncertainty and unit semantics.

```sh
python cli.py analytics Board.kicad_pro --price-field Rate --boards 10 --attrition-percent 5 --mass-field Weight_mg --mass-unit mg --power-field P_Loss --power-unit mW --group-by @type --format xlsx --output new-analytics.xlsx
python cli.py analytics Board.kicad_pro --config analytics-config.json --format csv --table groups --output new-mass-by-type.csv
python cli.py analytics Board.kicad_pro --metrics thermal --power-field P_Active --power-basis active --duty-field DutyPercent --temperature-field Temp_Max --temperature-requirement-c 80 --output new-thermal.json
python cli.py analytics Board.kicad_pro --stat Temp_Max=C --stat Mass=g --output new-stats.json
python cli.py threshold Board.kicad_pro --field Temp_Max --condition "<80" --unit C --rows --output new-under-80.json
python cli.py threshold Board.kicad_pro --field Temp_Max --condition "<80" --unit C --fail-on-match --fail-on-unknown
python cli.py query Board.kicad_pro --query 'Temp_Max<80 AND is:fit' --unit Temp_Max=C --rows
python cli.py gui --analytics-demo --no-auto-link
```

Output paths must be new. Non-JSON analytics requires `--output`; JSON without it uses the normal `wayricad-cli-1` stdout envelope. A saved analytics profile is loaded by default. `--config PATH` (or `-` for stdin) supplies a data-only `wayricad-analytics-config-1` object; explicit CLI flags override its values for this run and do not save them.

### Analytics flags

`--metrics pricing mass thermal` selects enabled metrics. The selected price field is per-unit by default; `--price-per 100` or `--price-per-field PRICE_BASIS` explicitly provides a pack denominator. Related mappings: `--currency-field`, `--currency-default`, `--moq-field`, `--multiple-field`, `--supplier-field`, `--sku-field`, `--quote-date-field`.

Physical mappings: `--mass-field`, `--mass-unit`; `--power-field`, `--power-unit`, `--power-basis average|active`, `--duty-percent`, `--duty-field`, independent `--rating-field`; `--temperature-field`, `--temperature-unit`, and `--temperature-requirement-c`. Map actual loss, not rated power, for dissipation.

Scenario/scope: `--scenario-name`, `--boards`, `--attrition-percent`, `--scenario-boards 1 10 100`, `--type-field`, repeated `--group-by`, and `--query`. Group pseudo-fields are `@type` and `@population`; other fields must exist. Repeated `--stat FIELD=UNIT` requests statistics. Repeated `--unit FIELD=UNIT` supplies default units for numeric filters, consistent with metric/statistics declarations. Quote the complete argument when a field contains spaces, e.g. `--stat "Maximum Temperature=C"`.

All additional settings, including manual FX, budgets, optional case sensitivity and the physical BOM-exclusion policy, are available through the JSON configuration. Configurations accept only their documented keys. `examples/analytics/analytics-config.json` is a complete validated example. There is no arbitrary formula/eval/shell execution facility in analytics configurations.

Formats: `json`, `csv`, `tsv`, `xlsx`, `html`, `txt`, `ascii` (alias `asc`), `md`, `zip`. Table names: `summary`, `components`, `groups`, `procurement`, `scenarios`, `statistics`, `issues`. Excel/HTML/JSON/ZIP contain complete reports; other formats select one table. They are advisory snapshots, not ordinary approved BOMs or recalculating Excel models.

`--fail-on none|error|warning|unknown` defaults to none. A chosen policy failure exits 3 and still emits the standalone diagnostic report. Existing invalid-input, I/O and stale-source exit behavior remains in effect.

### Threshold contract

`threshold` emits `wayricad-threshold-1`, including matched IDs/references, numeric coverage, separate unknown/invalid records, comparator/value and canonical unit. `--rows` adds complete matching BOM rows; `--query` narrows the tested scope. Missing/invalid numbers never satisfy compact numeric `!=`. Advanced-search `=`/`!=` remain text operators; `<`, `<=`, `>`, `>=` are unit-aware numeric comparisons. A threshold command does not connect to a live GUI or mutate its selections.

Saved/default unit mappings are used unless `--unit` overrides the threshold's default. Examples of recognized units: g/mg/ug/kg, W/mW/uW/kW, C/F/K, V/mV/kV, A/mA/uA, mm/cm/m, %/ratio and number. Bare numbers need the intended default unit; unsupported engineering/range labels remain invalid. Numeric money filters do not parse currency symbols or perform FX conversion; use a plain numeric rate property for those filters.

`--fail-on-match` exits 3 when there are matches. `--fail-on-unknown` exits 3 for any missing/invalid observation within the tested scope, even if there are no matches. Neither flag automatically changes a field or approves the nonmatching parts.

### Save analytics configuration through reviewed CLI changes

Create a configuration operation array:

```json
[
  {"op":"analytics-settings","settings":{"price_field":"Rate","mass_field":"Mass","mass_unit":"g","power_field":"Dissipation","power_unit":"W","statistics":{"Temp_Max":"C"}}}
]
```

```sh
python cli.py config preview Board.kicad_pro --changes analytics-changes.json --output new-analytics-plan.json
python cli.py config apply Board.kicad_pro --plan new-analytics-plan.json --confirm CONFIG
```

Inspect the plan first. This saves a sidecar profile, not native component properties. Reopen/reload any GUI after an external CLI write. CLI recipes must not write to the same sidecar concurrently with another user/process.

### Pipeline/job-set extensions

Add `analytics` to `reports`. `analytics` is either a configuration object or null for saved settings. `analytics_formats` supports JSON, CSV, XLSX, HTML; the complete JSON is always retained when the analytics stage runs, and CSV writes all seven tables. Set `policy.analytics` to none/error/warning/unknown deliberately; none is the default for old pipelines.

```json
{
  "schema":"wayricad-pipeline-1",
  "name":"BOM_With_Analytics",
  "variants":"all",
  "template":"Purchasing",
  "formats":["csv","xlsx"],
  "reports":["checks","analytics"],
  "analytics":{"price_field":"Rate","mass_field":"Mass","mass_unit":"g","budgets":{"mass_g":"100","power_w":"5","cost_per_board":{"INR":"5000"}}},
  "analytics_formats":["json","csv","xlsx","html"],
  "policy":{"checks":"error","health":"none","require_stock":false,"analytics":"error"}
}
```

A failed chosen gate writes diagnostics and a FAILED manifest but no ordinary BOM exports. `verify` validates bytes/hashes, not approval. The existing `run`, `jobset` and native Execute Command runner reuse this configuration unchanged. Native KiCad job-set execution is still untested in this environment.


# Version 0.6 additions — 33 command families total

All preceding commands remain. The following ten families use the same `wayricad-cli-1` envelope, strict data-only JSON and new-output path contract. Additional read reports default to advisory exit 0; explicitly requested gates return 3. Invalid/stale reviewed inputs are refused; inspect the diagnostic rather than retrying with a guessed confirmation. Mutating project commands save the sidecar; catalog/account/inventory operations commit to the separate local SQLite catalog.

## Catalog creation, harvest, revisions, evidence and native export

```sh
python cli.py catalog create --library /absolute/new-catalog --confirm CREATE
python cli.py catalog info --library /absolute/new-catalog
python cli.py catalog harvest /absolute/Board.kicad_pro --output harvest-plan.json
python cli.py catalog harvest /absolute/selected-projects --recursive --source-only --metadata-only --output source-observations.json
python cli.py catalog import --library /absolute/new-catalog --plan harvest-plan.json --confirm IMPORT --actor "Engineer Name"
python cli.py catalog search --library /absolute/new-catalog --query "10k 0603" --limit 50
python cli.py catalog health --library /absolute/new-catalog --all --market IN --freshness-hours 24 --low-stock 100 --output catalog-health.json
python cli.py catalog verify --library /absolute/new-catalog
python cli.py catalog edit-preview --library /absolute/new-catalog --request examples/engineering/new-catalog-part.json --output part-plan.json
python cli.py catalog edit-apply --library /absolute/new-catalog --plan part-plan.json --confirm CATALOG --actor "Engineer Name" --reason "Reviewed current manufacturer record"
```

Replace the fictional example part with correct real data before curation. Harvest defaults to saved sidecar data and captured supported assets; `--source-only` ignores sidecars, `--metadata-only` omits native asset capture. Directory scanning targets project files; explicitly supplied root schematics also work. Failed projects require a deliberate `--allow-partial` at import or correcting the scan. Source drift invalidates import.

Use returned exact catalog IDs with `catalog get --id ID [--revision N]`, `catalog evidence-preview --id ID --record evidence.json`, `catalog evidence-apply --plan PLAN --confirm IMPORT --actor NAME`, and `catalog native-export --ids ID1 ID2 --output new-native-library.zip`. The evidence record uses the documented exact manufacturer/MPN source/market/timestamp/review fields, not a raw supplier API response. `catalog export --output snapshot.json` exports metadata only, not a complete backup/restore database or its asset bytes. `catalog health` defaults to a page; `--all` explicitly scans every query match. Unknown stock is not a numeric zero.

## Independent BOM variants and recommendations

```sh
python cli.py bomvariant list Board.kicad_pro
python cli.py bomvariant preview Board.kicad_pro --request examples/engineering/bom-variant-derived.json --output variant-plan.json
python cli.py bomvariant apply Board.kicad_pro --plan variant-plan.json --confirm VARIANT
python cli.py recommend list Board.kicad_pro --library /absolute/catalog --component R1
python cli.py recommend preview Board.kicad_pro --library /absolute/catalog --component R1 --part-id RETURNED_EXACT_ID --output recommendation-plan.json
python cli.py recommend apply Board.kicad_pro --library /absolute/catalog --plan recommendation-plan.json --confirm EDIT --engineering-reviewed
```

`--variant` is accepted on project commands. Ref/UUID must be unambiguous. Optional recommendation `--fields` selects reviewed properties; generated/protected identities and expression-loss safeguards remain. Add `--acknowledge-loss` only when the inspected plan requires it. Part recommendations never automatically replace a library symbol or place a component. Catalog revision/source drift invalidates the plan.

Variant request ops are create, rename, reparent, metadata, lock, unlock and remove; all require a preview/VARIANT apply. Create chooses `mode: derived|pinned`; tags/description/parent are explicit. Pinned overrides retain raw expressions and copied variables, not a complete immutable source archive. BOM-only variants are excluded from native synchronization and remain in workspace exports/analytics. Native variant management keeps its prior restrictions.

## Mass suggestions and declared geometry qualification

```sh
python cli.py mass suggest Board.kicad_pro --library /absolute/catalog --field Mass --unit g --output mass-suggestions.json
python cli.py mass preview Board.kicad_pro --choices selected-masses.json --output mass-plan.json
python cli.py mass apply Board.kicad_pro --plan mass-plan.json --confirm EDIT --accept-estimate
python cli.py qualify Board.kicad_pro --component R1 --spec verified-land-pattern.json --require-match --output qualification.json
```

Mass `--library` is optional: without a supplied/attached/default library, the bounded built-in sources remain available. Use the same library at suggest/preview/apply when relying on catalog observations. `selected-masses.json` is an array of `{ "id": "RETURNED_COMPONENT_UUID", "option": "RETURNED_OPTION_ID" }`, not guessed mass numbers. Only blank mapped values can be filled. Source/basis/assumptions/uncertainty are retained. `qualify --require-match` returns 3 unless all implemented declared checks match; even a match is not an approval. Source drawings/identity/coordinates must be verified by a human.

## Inventory and multiple builds

```sh
python cli.py inventory list --library /absolute/catalog
python cli.py inventory preview --library /absolute/catalog --records inventory-lots.json --output inventory-plan.json
python cli.py inventory apply --library /absolute/catalog --plan inventory-plan.json --confirm INVENTORY --actor "Stockroom Name"
python cli.py buildplan Board.kicad_pro --library /absolute/catalog --config examples/engineering/build-scenario.json --output multi-build.json
```

Inventory fields: id, part_id, quantity, reserved, location, expires, status, source, observed_at, notes. Status is available/quarantine/scrapped; timestamps use ISO offset-aware input and dates use YYYY-MM-DD. Exact catalog IDs are mandatory. Upsert keeps omitted lots. Planning never reserves, deducts or buys.

Offer fields: id, part_id, supplier, sku, pool_id, available, observed_at, source_url, region, reviewed, lead_days, currency, unit_price, moq, multiple, tiers. Tiers are `{ "min_qty": 100, "unit_price": "0.10" }` records. Numeric lead days must be supplied for due-date coverage. Split sourcing requires both explicit allow_split and independent_pools_reviewed. Costs remain separate by currency. Use `--require-covered` to return 3 when the result has gaps/review issues; advisory reports are still generated. This is greedy priority simulation, not a global optimum or supplier promise.

## Local reviewers and controlled pipeline gates

```sh
python cli.py review register --library /absolute/catalog --name "Local Admin" --role admin --confirm REGISTER
python cli.py review register --library /absolute/catalog --name "Engineer Name" --role engineering --admin "Local Admin" --confirm REGISTER
python cli.py review accounts --library /absolute/catalog
python cli.py review context Board.kicad_pro --library /absolute/catalog --policy examples/engineering/review-policy.json --output review-context.json
python cli.py review decide Board.kicad_pro --library /absolute/catalog --policy examples/engineering/review-policy.json --decision reviewed-decision.json
python cli.py review context Board.kicad_pro --library /absolute/catalog --require-approved
python cli.py review ledger --library /absolute/catalog
```

Prompts are hidden. For automation, `--password-env VARIABLE_NAME` selects an existing environment variable; registering additional accounts can also use `--admin-password-env ADMIN_VARIABLE`. These arguments name variables, not secret values. Never put `password` in JSON. Noninteractive invocation without a suitable environment variable refuses instead of reading a visible passphrase from stdin. `review deactivate` needs name, admin, admin passphrase and `--confirm DEACTIVATE`.

Decision JSON: kind (`release|waiver|qualification|alternate|revoke`), reviewer, role, reason (10+ characters), evidence, target, expires_at, input_hash and confirmation `REVIEW`. Take input_hash and exact finding/qualification/alternate target hashes from the fresh context. For release, target may be blank; for revoke, use the exact prior decision ID and admin account. Expiry must be a future offset-aware timestamp no more than 366 days away. Use exactly the same policy at context and decide. Catalog changes or relevant project/geometry/evidence drift invalidate a review.

`release_control` is an OPTIONAL pipeline key:

```json
{
  "library": "/absolute/catalog",
  "policy": {
    "roles": ["engineering", "supply"],
    "check_level": "error",
    "catalog_required": true,
    "stock_required": true,
    "qualification_required": false,
    "market": "IN",
    "freshness_hours": 24
  }
}
```

Insert this object under `release_control` in a valid existing wayricad-pipeline-1 configuration. Other previous check/health/analytics policies remain separate. The gate writes controlled-review reports, refuses ordinary BOM outputs on failure and rechecks before publication. It does not perform native APPLY or automatically obtain reviewer approvals. Native job sets reuse the same pipeline runner. A signature-valid local decision is not a public-key signature of the resulting files.

## Real host recorder, measured benchmark and GUI sample

```sh
python cli.py hosttest --project /absolute/disposable/Board.kicad_pro --directory /absolute/new-host-output
python cli.py benchmark --parts 10000 --queries 100 --output new-benchmark.json
python cli.py gui --engineering-demo --no-auto-link
```

Hosttest executes installed native commands on a bounded copy; absent kicad-cli returns 6 with SKIPPED/UNAVAILABLE, failed executed checks return 3. Manual checks remain NOT_EXECUTED. This development release has not passed real native acceptance. Benchmark uses temporary synthetic SQLite metadata, warm-cache exact-MPN queries and integrity checks. It is not a production project parse, native editor or screen-reader benchmark. GUI can still use `--detach`; session URLs remain private.


## v0.7 catalogue assets and independent searching

All commands below require only --library, not an open project. There are still 33 top-level command families; the new operations are catalog subcommands. Global CLI exit/envelope rules remain unchanged.

```sh
python cli.py catalog search --library /local/catalog --query "10k" --has-asset all3
python cli.py catalog search --library /local/catalog --status preferred --kind orderable --filters field-filters.json
python cli.py catalog assets --library /local/catalog --id PART_ID --output asset-manifest.json
python cli.py catalog preview --library /local/catalog --id PART_ID --kind symbol --unit 1 --style 1 --format svg --output symbol.svg
python cli.py catalog preview --library /local/catalog --id PART_ID --kind footprint --format svg --output footprint.svg
python cli.py catalog preview --library /local/catalog --id PART_ID --kind model --model-index 0 --output model-mesh.json
python cli.py catalog asset-export --library /local/catalog --id PART_ID --hash ASSET_SHA256 --output original.step
python cli.py catalog harvest /projects --recursive --asset-config asset-paths.json --output harvest-plan.json
python cli.py catalog import --library /local/catalog --plan harvest-plan.json --confirm IMPORT --actor "Your name"
python cli.py catalog native-export --library /local/catalog --ids PART_ID --choices source-choices.json --require-complete --output full-library.zip
```

Use returned part IDs rather than schematic references. assets/preview support --revision and --set-id; asset-export supports --revision. Preview kinds: symbol, footprint, model; format is json by default, or svg for the two native 2D views. A mesh result is portable data, not a launched KiCad viewer. Model preview uses one declared model index at a time and reports original transforms; it is not a footprint overlay.

Search: --has-asset symbol|footprint|model|all3|incomplete; --status candidate|preferred|deprecated|blocked; --kind generic|orderable; optional exact --footprint; --limit 1..500 and --offset. The custom --filters file is an array of AND clauses, applied to all text matches before pagination:

```json
[
 {"field":"Temp_Max","op":"<","value":"80","unit":"C"},
 {"field":"MPN","op":"present"}
]
```

Missing/invalid numbers do not pass numeric filters. Text and numeric equality are separate operators: equals versus numeric_equals. See V7_WORKFLOWS.md for all operators. Source choice JSON maps a current part ID to a returned asset-set ID, e.g. {"p_...":"SHA256_SET_ID"}; omit --choices only when the source is unambiguous. --model-prefix can replace the default ${KIPRJMOD}/WayriCAD.3dshapes with a configured local KiCad variable prefix. Quote dollar expressions according to your shell.

Native ZIP export is partial-capable by default in CLI; explicitly add --require-complete for self-contained references. The GUI defaults this option on. Export refuses back-side board normalization and mismatched current footprint metadata. Direct original-asset output must retain the correct .kicad_sym/.kicad_mod/model extension and be new. A symbol asset is a single captured definition wrapped in a library container, not the original whole library file. Model downloads preserve exact bytes. Ordinary automation cannot write native design files.

Only asset-bearing harvest-plan reads accept up to 384 MiB, with the same duplicate-key/nonfinite-key safeguards; other JSON inputs retain 20 MiB. Individual assets are capped at 64 MiB and scans at 256 MiB unique asset bodies. No remote model paths, scripts, textures or external auxiliary files are followed. Existing --metadata-only deliberately skips capture. No old catalogue can recover unstored 3D originals without re-harvesting.

STEP/IGES/BREP preview requires the optional requirements-preview.txt in this interpreter. Embedded decoding needs an available system/KiCad zstd library or requirements-assets.txt. Doctor reports module detection, not host certification. Unknown geometry or decoder errors remain visible. All conversion is bounded/cancelable; no preview is a release qualification.


# Version 0.8.2: Vendor-split uploads (38 command families)

## CLI and job sets

There are **38 command families**, including the new `vendors`. From the installed plugin directory:

```powershell
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --vendor-field Supplier --boards 20 --format json --output ".\routing-review.json"
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --vendor-field Supplier --boards 20 --format zip --output ".\vendor-boms.zip"
py -3 .\cli.py vendors "C:\Projects\Board\Board.kicad_pro" --format xlsx --vendor mouser --output ".\Mouser.xlsx"
```

`--config FILE` or `--config -` accepts the same data-only configuration. Optional `--fingerprint` requires the exact preceding review. `--allow-partial` is explicit. `--save-settings` deliberately saves the mapping in the sidecar and is incompatible with `--source-only` or binary/file output. Ordinary reads/exports never save. A vendor JSON preview exits 3 on blocked/incomplete demand unless explicitly permitted partial; its report is still emitted. Binary failures produce a diagnostic receipt and no output file. Output files must be new; nothing is overwritten.

Release pipelines can add `"vendor_exports": { ...vendor configuration... }`. Missing/null leaves earlier behavior unchanged. An enabled vendor step reports per-variant routing, and any unresolved demand or source error fails the pipeline. No partial pipeline uploads are allowed. All gates must pass before ordinary BOMs and vendor `uploads/` files are published. Job sets generated by the existing tool use the same pipeline and runner. All-excluded variants retain audit-only files and do not fail for zero purchasing demand. Sample configuration is in `examples/vendor_splitting/pipeline-vendors.json`.

## Source references and acceptance limits

Profile references checked 10 September 2026:
- DigiKey myLists / BOM help: https://www.digikey.com/en/help-support/place-an-order/build-a-bom
- DigiKey myLists: https://www.digikey.com/en/mylists
- Mouser official FORTE upload demonstration: https://www.youtube.com/watch?v=xwwTFMKBxjg
- Mouser-authored demonstration transcript: https://www.linkedin.com/posts/mouser-electronics_how-to-create-a-bill-of-materials-using-the-activity-7092237130877288448-Sf0L
- Mouser BOM: https://www.mouser.com/bom/

Local output parsing, quantity reconciliation, UI downloads, pipeline failure behavior and integrity are tested. Actual supplier-site uploads and actual KiCad/Windows/macOS/embedded-window/IPC host operation remain unexecuted. Read TEST_REPORT.md for exact results. No API credentials, live prices, cloud scraping, telemetry or buying action was added.


## 0.8.3: assemblers (39 command families)

The `assemblers` command is separate from purchasing `vendors`. See V83_ASSEMBLER_WORKFLOWS.md for complete syntax, required review, per-board quantity semantics and `assembler_exports` pipelines. `python cli.py assemblers --help` lists every supported option. `--list-profiles` is project-free. All native-first, explicit write-review and new-output-path rules remain in force.
