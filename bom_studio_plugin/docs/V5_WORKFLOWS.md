# WayriCAD BOM Studio 0.5 — Cost, mass, dissipation and threshold analytics

Developer preview · 9 September 2026. The quantitative engine is implemented and shared by GUI, CLI and release/job-set pipelines. These are auditable calculations over entered component data, **not** price discovery, mechanical qualification, a thermal solver or engineering approval.

## 1. Start with the synthetic sample

From the distribution folder, run **TRY_ANALYTICS_SAMPLE_WINDOWS.bat** or `sh ./start_bom_studio.sh --analytics-demo`. A temporary copy is created; the original example is not changed. Choose **Cost, mass & power → Run analytics**. The example profile maps `Rate`, `Mass`, `Dissipation`, `ComponentType` and `Temp_Max`.

All sample numbers are fictional. C3 deliberately has missing mass; R4 is DNP and has an unknown temperature rating; J1 has a deliberately low maximum temperature. The example has INR 53 known installed component cost/board, 1.43 g known component mass with only 9 of 10 eligible masses present, and 0.038 W entered operating dissipation/board. **1.43 g is a subtotal, not a complete board mass.** These numbers are demonstration arithmetic, not actual component specifications.

For real designs, first stage/save the intended BOM field edits. The GUI uses committed workspace data; unreviewed grid drafts are not included. CLI reads the saved native files and saved `.wayricad-bom.json`, not unsaved browser/KiCad memory.

## 2. Map your own columns

Open **Input fields, units, population scope and assumptions**. Choose any existing property for the unit/pack rate, mass, operating dissipation, type and optional ratings. The field-name suggestions do not restrict you to canonical `UnitPrice` or `Mass` names. Mapped fields may use the existing resolver's supported KiCad expressions. The report records the actual raw property name, original expression and resolved value for the principal source fields.

Three separate actions are important:

* **Run analytics** computes a read-only report using the current form, without changing properties, settings or native files.
* **Save settings to workspace** stages the validated analytics profile in memory. **Save workspace** persists it in the sidecar. The top Save workspace action also saves a pending analytics mapping draft, including after navigating to another view.
* **Export analytics** recomputes the report from the current mapping/settings; it does not export an obsolete cached report. Saved native design files remain unchanged.

Reports show a stale warning after settings, variant or workspace changes. Re-run after editing. A setting-only change can invalidate the cached report even if the numeric result would be unchanged. Invalid/source-drift conditions are reported, not silently ignored.

**Existing ordinary BOM templates are not rewritten by an analytics mapping.** The BOM workspace's cost KPI uses the saved price mapping over the full active variant. Ordinary Purchasing exports still use their existing configured columns and aliases. Use the new analytics export for the mapped financial/physical reports, or intentionally adjust the ordinary template/aliases separately. A filtered analytics subset can legitimately differ from the full-variant workspace KPI.

## 3. Price analysis

Map the **Rate / price field** and currency field. A rate is the price for one component by default. For a price per 100 pieces, set **Rate is per N pieces = 100**, or select a per-row divisor property. A selected divisor property must contain a positive integer for every priced record; missing/zero/invalid values do not fall back to 1. Do not select an already extended line total without supplying its correct divisor.

The price parser accepts finite dot decimals, optional English thousands separators, explicit currency-code prefixes/suffixes such as `INR 12.50`, and supported currency symbols with compatible currency context. Contradictory currencies are invalid. Ambiguous symbols do not guess a different currency from the explicit/default code. Decimal comma and Indian lakh-style grouping are not guessed; normalize imports to dot decimals and ungrouped numbers or supported English grouping. Negative prices are invalid; entered zero is a known price.

For each currency, the report separates:

| Result | Meaning |
|---|---|
| Installed cost / board | Known normalized unit prices for fitted, BOM-included components |
| Installed build cost | Installed cost multiplied by the chosen build count |
| Required cost | Quantity including the configured purchasing attrition allowance |
| Order cost | Required quantity raised to MOQ and order-multiple constraints |
| Overbuy cost | Extra ordered quantity beyond the required quantity, separately from attrition |

For each compatible procurement lot:

```text
unit_price = entered_rate / price_per_units
installed_qty = quantity_per_board * boards
required_qty = ceil(installed_qty * (1 + attrition_percent / 100))
order_qty = ceil(max(required_qty, MOQ) / order_multiple) * order_multiple
attrition_qty = required_qty - installed_qty
overbuy_qty = order_qty - required_qty
```

Blank MOQ/multiple means 1; malformed supplied policy data makes the relevant order subtotal incomplete. Pooling uses the complete exact manufacturer/MPN identity plus value, footprint, supplier/SKU, currency, price/divisor, quote date and order policy. Missing identities are not pooled across different physical records. Reference/value/type display grouping never permits incompatible purchasing identities to merge.

Missing rates are never treated as zero. Pricing coverage and incomplete order lines are reported independently. Known order cost can be a subtotal when some rates or order policies are missing. The currencies are not automatically summed together.

**Cost & Pareto** ranks the chosen breakdown groups by contribution to known cost, with shares, cumulative shares and an ABC classification. A group starting below 80% cumulative known cost is A, below 95% is B, otherwise C. This is a contribution classification, not evidence of savings, interchangeability or a purchasing recommendation. A single dominant group remains A even if it crosses a boundary.

## 4. Currencies, quotes and quantity scenarios

Optional manual FX is in **Budgets, FX & statistics**. A rate means **base-currency units per 1 source-currency unit**. Enter a base currency, explicit rates, observation date and source. The base-to-base rate must be 1. Missing conversion rates leave the consolidated result partial/unknown; they do not become zero or an implicit exchange rate. FX is user-supplied and not live or independently authenticated. Its stated date does not establish market validity.

The selected price-date property is assessed against the configured maximum age (default 90 days). Stale, future or invalid dates produce warnings. Those prices remain arithmetic inputs. Undated quotes are counted explicitly and are not automatically treated as current; requiring a date on every quote is not a release rule in this build.

Build scenarios recalculate the same rate data at configured quantities, applying MOQ/multiple/attrition separately for each build size. They do **not** infer supplier price breaks or automatically optimize split suppliers/orders. Taxes, freight, manufacturing labor, NRE and exchange-rate changes are not included. Source price/evidence ledgers are not silently changed by analytics.

## 5. Mass tables and physical population

Map the per-component mass property and default unit: `g`, `mg`, `ug` (including µg/μg input) or `kg`. Explicit supported units within cells override the default unit for bare numbers, but must be the same dimension. `250 mg`, `0.25 g` and `0.00025 kg` represent the same mass.

Mass counts **fitted on-board components**, including BOM-excluded on-board items by default. Disable that policy deliberately when the intended scope excludes them. DNP/DNI and off-board parts do not add physical mass. The parser's physical component instances are counted, not every graphical multi-unit symbol. Repeated-sheet physical instances remain separate.

Purchasing spares, attrition, MOQ and overbuy do **not** increase installed mass. Installed build mass is per-board mass times board count. The tool cannot include a PCB substrate, solder, conformal coating, enclosure, harness or loose hardware that is absent from its component records and supplied mass data. Do not treat this as a complete assembly weigh-in or infer mass from footprint/package names.

The type/field breakdown and component table include mass values, counts and missing-data coverage. A custom type property takes precedence; otherwise a conventional reference-prefix heuristic is explicitly labelled. You can use any exact property or combination (up to eight fields) as the breakdown: `@type`, `@population`, manufacturer, footprint, sheet, subsystem or custom fields. Enter one field per line; `@type` and `@population` are the two synthetic keys.

## 6. Thermal dissipation, ratings and temperature limits

Map an **actual operating dissipation** property, not a component's absolute-maximum or rated-power label. Units are `W`, `mW`, `uW` (µW/μW input) and `kW`; plain fractions such as `1/4 W` are accepted. SI prefix case matters. A negative loss is invalid; a deliberately entered zero is known.

Choose exactly one interpretation:

| Basis | Calculation |
|---|---|
| Already average | Entered dissipation, unchanged; duty settings are not applied a second time |
| Active-state power | Entered active loss × configured duty percentage / 100 |

A per-component duty-percent field can override the global duty setting. When that field is mapped, each relevant record needs a known value from 0 to 100; missing duty is unknown, not 100%. A ratio can be explicit, e.g. `0.25 ratio` = 25%, but a bare `0.25` in a percent field is 0.25%, not 25%.

The sum represents the entered operating scenario for one board. A batch of 100 boards is not assumed to be powered simultaneously. Component and group tables retain input/active power, applied duty and average power. The optional independent rated-power field can flag entered dissipation above the stated rating and report a utilization ratio. It does not apply temperature derating or establish suitability.

The maximum-temperature field accepts C, F and K. Bare values use the selected default. Optional **Required operating temperature (°C)** compares the supplied maximum rating against a user-defined requirement and reports the arithmetic difference. Verify that all mapped values represent the same intended operating-temperature rating; junction, storage and ambient limits are not interchangeable.

**No junction-temperature prediction, thermal resistance network, heat-flow map, airflow, spatial coupling, duty transient, PCB thermal simulation or safety qualification is performed.** Adding a maximum rating cannot fill a missing operating dissipation value. Missing geometry/data cannot become a thermal pass.

## 7. Threshold searches: `<80` in `Temp_Max`

In the BOM view choose **Column threshold…**, or the menu beside any displayed field header. Choose **Temp_Max**, enter **`<80`**, select the bare-number unit (or use the saved analytics mapping), then **Test threshold**.

The preview shows matched references, tested count, numeric coverage and unknown/invalid records. There are two distinct actions:

* **Filter to matches** shows only matching rows, intersected with other active view filters before grouping/pagination.
* **Highlight matches** keeps other rows visible but marks only matching rows and containing groups. The group's actual member values remain available on expansion.

Neither action checks edit-selection boxes. **Use Select all results or explicit checkboxes before bulk editing.** Filtering/highlighting never changes native files or component properties. Clearing a threshold restores the other active filters. Live-link temporary reveal can bypass view filters deliberately; it does not rewrite the threshold definition.

There is one compact threshold at a time. Combine more predicates using **Advanced search**, for example:

```text
Temp_Max<80
is:fit AND Temp_Max<80
Mass>"250 mg" AND Dissipation>"100 mW"
NOT is:dnp AND (Temp_Max<80 OR missing:Temp_Max)
```

Supported numeric threshold operators: `<`, `<=`, `>`, `>=`, `=`, `!=`. In the compact numeric dialog/CLI, even `!=` excludes missing/invalid observations. In the existing advanced language, `=` and `!=` retain their **text equality** meaning for compatibility; use the compact numeric threshold command for unit-normalized equality. Negating a numeric predicate in the boolean query follows normal boolean logic; explicitly add missing/invalid rules when that matters.

Saved mappings define units for bare numbers. A numeric literal with an explicit unit can establish a dimension when none is mapped. C/F/K are converted to Celsius; mass to grams, power to watts. Unknown fields and bad conditions fail closed. Unsupported ranges (`-40 to 125`), mixed dimensions, currency-bearing numeric-filter text and executable/math expressions are not guessed. A raw `${VARIABLE}` expression is not itself numeric; use its resolved field when appropriate.

`query --unit FIELD=UNIT` can override a default for that one read-only query. Reusable settings cannot give the same physical field contradictory default units across metrics/statistics/filters. Share the analytics unit profile along with saved searches that depend on bare-number units. The compact highlight state itself is session-only, not a saved global conditional-formatting rule.

## 8. Budgets, coverage and general numeric statistics

Per-board cost budgets are entered separately by currency, plus a component-mass budget in grams and dissipation budget in watts. Each produces a status:

* **Exceeded:** the known subtotal already exceeds the limit, even if other data is missing.
* **Unknown:** the subtotal is below the limit but eligible data is incomplete, or no known total exists.
* **Within known budget:** the selected metric has complete supplied data and its total is within the limit. This is arithmetic, not engineering approval.

Add numeric-statistics field/unit mappings in **Budgets, FX & statistics**, such as `{"Temp_Max":"C","Mass":"g","LeadTime":"number"}`. Statistics report count, missing/invalid counts, minimum, maximum, mean, median, nearest-rank 95th percentile, extrema references and an eight-bin histogram in JSON. The GUI has the summary table; it does not draw every histogram. Statistics cover **all query-matched records**, including DNP unless your analytics query excludes them. Physical mass/power totals keep their own fitted/on-board scope.

No normal-distribution assumption, reliability score, electrical qualification or interchangeable-part conclusion is inferred from descriptive statistics.

## 9. Export reports

Analytics supports JSON, CSV, TSV, XLSX, HTML, Unicode fixed-width text, strict 7-bit ASCII (`.asc`), Markdown and ZIP.

CSV/TSV/text/Markdown can select `summary`, `components`, `groups`, `procurement`, `scenarios`, `statistics` or `issues`. JSON includes the complete structured report. Excel contains **Summary, Components, Groups, Procurement, Scenarios, Statistics, Issues and Provenance**. HTML includes every report section; ZIP includes the full JSON/XLSX/HTML, seven CSVs and a per-file SHA-256 manifest. These are additional report exports; ordinary BOM exports retain their wider pre-existing format set.

XLSX values are calculated snapshots, not recalculating Excel models. Native user strings are not spreadsheet formulas. Computed numeric cells are stored numerically when within Excel's precision limit; longer exact decimals stay text. Missing quantities stay blank with accompanying status/coverage, never numeric zero. The formula-free snapshots are regenerated by the same engine in GUI/CLI, rather than relying on a spreadsheet application to evaluate manufacturing evidence. CSV prefixes that could execute as formulas are escaped. ASCII escapes unsupported characters visibly. No data is silently truncated to fit a column; large text may require expanding rows or using the full JSON/CSV output.

Reports/settings can contain proprietary rates, source paths, reference lists, notes, variable expressions and supplied FX source strings. Inspect before sharing. Integrity hashes are not signatures, trusted author identities or purchasing approvals.

## 10. CLI and job-set pipelines

`CLI_REFERENCE.md` gives the full commands. From the plugin folder:

```sh
python cli.py analytics Board.kicad_pro --price-field Rate --mass-field Mass --mass-unit g --power-field Dissipation --power-unit W --group-by @type --format xlsx --output new-analytics.xlsx
python cli.py analytics Board.kicad_pro --metrics mass --mass-field Weight_mg --mass-unit mg --group-by ComponentType --format csv --table groups --output new-mass-table.csv
python cli.py analytics Board.kicad_pro --metrics thermal --power-field P_Loss --power-basis active --duty-percent 40 --temperature-requirement-c 80 --output new-thermal.json
python cli.py threshold Board.kicad_pro --field Temp_Max --condition "<80" --unit C --rows --output new-under-80.json
python cli.py query Board.kicad_pro --query 'Temp_Max<80' --unit Temp_Max=C --rows
```

Analytics defaults to exit 0 even with advisory findings. Add `--fail-on error|warning|unknown` deliberately. `threshold --fail-on-match` can enforce your own limit, and `--fail-on-unknown` requires complete numeric coverage in its tested scope; either failure exits 3. JSON output includes references/IDs, not a GUI side effect. Standalone report output remains available for failed advisory policies.

A pipeline may add `analytics` to `reports`, supply a profile under `analytics`, choose `analytics_formats` (JSON, CSV, XLSX, HTML), and choose `policy.analytics`. A null profile uses the saved workspace settings. An explicit embedded profile is portable data, not executable code. The GUI's **Include current analytics settings in this pipeline** captures the current mapping without turning on a blocking policy silently.

A chosen failed gate publishes diagnostics and a FAILED manifest, **not ordinary BOM exports**. Passing means the selected configured gates passed, not that absent/disabled metrics were qualified. KiCad Execute Command job sets reuse this same runner/configuration; no separate thermal or price logic is hidden in GUI automation. Native KiCad job-set execution remains a target-system acceptance task.

## 11. Boundaries and future work

This build does not provide live pricing, inferred quantity discounts, stock allocation across suppliers, complete assembly mass, center-of-gravity/inertia, PCB spatial heat maps, automatic derating models, forecast temperatures or risk-qualified substitution. More extensive costing (taxes, labor, shipping/NRE), recorded supplier price-break curves, all-variant mass/cost-delta dashboards, uncertainty distributions and measured assembly-mass reconciliation remain future extensions. The current engine can generate independent per-variant/scenario reports through a pipeline without pretending to implement those broader analyses.

Use a disposable project copy for initial verification. KiCad-host launch/reload, real IPC selection transport/relay, native job-set execution, Windows/macOS installers and genuine KiCad 11 behavior remain untested here. See `TEST_REPORT.md` for what was actually executed.
