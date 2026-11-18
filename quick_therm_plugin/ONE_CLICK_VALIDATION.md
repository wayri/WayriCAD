# Automatic Run validation

Source branch: `codex/quicktherm-one-click`, based on
`d481ee90ac67edd780ddfe88c40db79c8dd6fd60`. This is a local source update,
not a published release or a completed local installation.

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

## Checks and remaining gates

- New native automatic-Run regression passed: model selection, blank defaults,
  edited-value retention, manual mesh, old-study migration, explicit unknown
  source rejection and unsupported layer-only study rejection.
- Screening setup: 4 tests passed. Source documentation validation passed.
- Broad native pytest run: 323 passed, 3 skipped, 223 subtests passed; three
  Windows inherited-stdin failures were identified. Explicit DEVNULL stdin and
  UTF-8 diagnostics were added without changing behavioral assertions.
- Follow-up native subset: 7 passed, 2 timed out (heating-guide lifecycle and
  multi-selection). These are unresolved; a fully green native suite is not
  claimed. The normal real-board Run and new automatic-mode test passed.
- An earlier Python 3.14 source-suite run was interrupted and is not acceptance
  evidence.
- A single-plugin PCM was built and inspected on D:, with 221 payload files
  and 8,697,176 uncompressed bytes. No suite-wide feed was changed.
- Installation and installed-payload validation were suspended when C: crossed
  the explicitly authorized 18 GiB minimum. The last observed capacity was
  17.29 GiB on C: and 430.17 GiB on D:. No existing user data was removed.

Complete the remaining native checks and install with a verified backup after
capacity is restored above the authorized threshold. Keep local result files,
test logs and machine paths out of published packages.
