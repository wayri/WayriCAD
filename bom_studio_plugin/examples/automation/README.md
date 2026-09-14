# Automation examples

Use on a disposable project copy and review every recipe. These are inputs, not automatically executed actions. `pipeline-default.json` blocks BOM-data errors but leaves health advisory. `pipeline-strict.json` also rejects health unknowns and insufficient eligible stock evidence; it is expected to fail on the synthetic demo. `bulk-standardize-value.json` deliberately edits Value, without changing MPN or qualifying a replacement. `bulk-review-notes.json` demonstrates ordered transforms. `config-create-variant.json` adds a review variant and filter; choose different names when they already exist. Import the filter bundle through Advanced search.

From the plugin directory:

```sh
python cli.py run examples/BOM_Demo.kicad_pro --config examples/automation/pipeline-default.json --output-dir /existing/parent/new-release
python cli.py bulk preview examples/BOM_Demo.kicad_pro --recipe examples/automation/bulk-review-notes.json --output /existing/parent/new-plan.json
```

Preview does not apply. Read `docs/CLI_REFERENCE.md` for explicit apply commands, native synchronization, job sets and exit codes. Output paths must be new. Do not share release snapshots or plans without reviewing private data.
