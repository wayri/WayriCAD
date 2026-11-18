# Automatic Run validation

Source branch: `codex/quicktherm-one-click`, based on
`d481ee90ac67edd780ddfe88c40db79c8dd6fd60`. This records source validation;
publication and installed-payload evidence are recorded in the release receipt.

## Behavior

Automatic setup is enabled for new windows. Run enables the board model and
automatic mesh, selects a supported saved stackup or labelled thin-sheet screen,
and fills blank starting ambient/material inputs without replacing edits.
Explicit model/manual-mesh actions leave automatic mode. Older saved studies
migrate to advanced mode, preserving their settings. Unknown selected powers,
conflicting boundaries and unsupported layer-dependent physics remain errors.

## Execution evidence

Windows, KiCad 10 native bindings, existing managed Python 3.11 scientific
runtime. No dependencies were installed. Numerical inputs below are illustrative;
these checks establish execution and energy balance, not measured accuracy.

| Board | Source SHA-256 | Inputs | Heat-balance residual |
| --- | --- | --- | --- |
| Public thermal demo | `1cfc57ddd9bb546f22ad6984c961ce0745ec1c0f7b9203f749574ade49c9c3ee` | C1=0.25 W, C2=0.5 W, ambient=25 C | 2.22e-16 W |
| KERO Encoder | `8d8949f170cca1f9030f9c20379f2b27ebe0634a66362e7194f6f6299c876a54` | U1=0.5 W, R1=0.1 W, ambient=25 C | 3.33e-16 W |

Both native-window runs used the normal asynchronous worker path, automatically
included known power with no initial component selection, converged and retained
unchanged PCB hashes. Junctions remained unknown without package data. The
Encoder run is a thin-sheet screen, not a layer-resolved accuracy claim.

Reproduce on an existing board using the current source and its prepared runtime:

```text
python tools/verify_quick_therm_quick_start.py --worker-python <prepared-python> --board <Encoder.kicad_pcb> --power U1=0.5 --power R1=0.1 --ambient 25 --output <result.json>
```

The verifier also accepts `--plugin-root <installed-plugin-directory>` to reject
source-runtime fallback when checking the final installed payload.

## Checks

- New native automatic-Run regression passed: model selection, blank defaults,
  edited-value retention, manual mesh, old-study migration, explicit unknown
  source rejection and unsupported layer-only study rejection.
- Screening setup: 4 tests passed. Source documentation validation passed.
- Broad native pytest run: 323 passed, 3 skipped, 223 subtests passed; three
  Windows inherited-stdin failures were identified. Explicit DEVNULL stdin and
  UTF-8 diagnostics were added without changing behavioral assertions.
- An intermediate follow-up had two UI timeouts. Both tests subsequently passed
  in isolation and in the complete native suite. Native launches now isolate
  stdin, use UTF-8 file diagnostics where needed, replace the startup placeholder
  before selection assertions, and retain bounded traceback diagnostics. No
  numerical tolerance, behavioral assertion or timeout was weakened.
- Final complete native suite: **326 passed, 3 skipped, 223 subtests passed** in
  173.69 seconds. All three skips require optional Gmsh/CalculiX integration
  dependencies or opt-in; the built-in solver and native UI checks ran.
- An earlier Python 3.14 source-suite run was interrupted and is not acceptance
  evidence.
- A single-plugin PCM was built and inspected on D:, with 221 payload files
  and 8,697,176 uncompressed bytes. No suite-wide feed was changed.
- Local work was suspended below the authorized 18 GiB C: minimum. A separately
  coordinated verified cleanup restored capacity before final native validation.
  Temporary outputs remained on D:. No user board or shared cache was removed
  by this QuickTherm task.

The release receipt records exact final CI, installer hashes, local backups and
installed-payload acceptance. Keep local result files, test logs and machine
paths out of published packages.
