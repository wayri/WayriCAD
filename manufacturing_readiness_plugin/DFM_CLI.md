# DFM / DFA Command-Line Guide

Install the suite CLI as described in [runtime setup](../wayricad_runtime/RUNTIME_SETUP.md).
The commands below need Python but not wxPython or pcbnew. Native audits need
the matching KiCad CLI. No source project files are rewritten. Temporary output
uses the operating system's configured TEMP/TMP directory.

## Discover and Review a Process

```sh
python -m manufacturing_readiness_plugin.dfm_cli --help
python -m manufacturing_readiness_plugin.dfm_cli vendors --query "OSH Park" --layers 4
python -m manufacturing_readiness_plugin.dfm_cli preview --profile lion-mii-1oz --context '{"board_type":"rigid","layers":2,"copper_oz":1,"copper_basis":"vendor_order_option"}'
```

The JSON context must include every scoped field required by the selected
profile. Use its `process` object to choose an individual supported layer count,
copper weight and finish; do not send the arrays themselves. Copper basis is
`starting`, `finished`, or `vendor_order_option`. Inner copper is independent.
Run `preview` before DRC to inspect compiled constraints and omissions.
PowerShell users can pass the same single-quoted JSON argument; legacy Windows
PowerShell native argument quoting may require running from Python or another
shell when embedded double quotes are stripped.

## Audit a Saved Board

```sh
python -m manufacturing_readiness_plugin.dfm_cli audit Example/board.kicad_pcb --profile lion-mii-1oz --context '{"board_type":"rigid","layers":2,"copper_oz":1,"copper_basis":"vendor_order_option"}' --confirm-process > vendor-audit.json
```

`--confirm-process` records your explicit process/quote confirmation; it is not
automatically inferred. `--cli` chooses an installed executable and `--timeout`
sets a positive seconds budget. An explicit originating-host CLI environment
selection remains authoritative when no command-line override is supplied.
Use `--profile-file custom-process.json` instead of `--profile` for reviewed
custom input. The file is validated, bounded to 2 MiB and never merged into the
bundled catalogue. JSON on stdout contains source hashes, profile, context,
timestamp, native findings and check status. Errors are JSON on stderr.

| Exit | Meaning |
|---|---|
| 0 | Completed; all recorded requirements PASS or N/A |
| 1 | Native findings or a failed requirement; inspect the JSON |
| 2 | Invalid inputs, missing CLI, native execution failure or stale source |
| 3 | Completed without native failures, but requirements remain UNKNOWN |
| 130 | Interrupted; no accepted result |

Manual engineering requirements normally make a clean screening run exit 3.
Do not replace this with a CI success that claims assembly qualification.
For example, a workflow may retain the report as an artifact for exits 1/3,
but must still require review before manufacturing release. Run ordinary
project DRC separately: vendor-mode rules replace custom rules only in the
private copy, while manual-only profiles run project DRC without inventing
vendor limits. The Manufacturing Readiness Manager's jobset and deterministic
release gates remain a separate workflow; this command does not release a PCB.

## Troubleshooting

- **Unknown/incompatible scope:** choose the exact service/copper basis and all
  required process fields. Never substitute a different vendor's limits.
- **Layer mismatch:** the saved PCB layer table, not the live editor's unsaved
  setup, must match the selected process.
- **CLI code or rule diagnostics:** check KiCad version compatibility and custom
  profile syntax. Diagnostics cannot produce a passing result.
- **Source changed:** save and rerun against the new PCB/project/rules revision.
- **Missing supplier limits:** export a related profile as a schema example,
  give your custom profile a new ID and attach actual official/quoted sources.
  Unverified or unsupported rules stay omitted/manual.
