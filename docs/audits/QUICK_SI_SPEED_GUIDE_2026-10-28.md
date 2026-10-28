# Quick SI speed and guide validation — 28 October 2026

Validated on Windows with KiCad 10.0.6, its Python 3.11.5 and native pcbnew/wx. Baseline: source commit `e4a3e684`. This is a first-analysis comparison, not a warmed persistent result-cache comparison.

## Changes

- Reuse exact corridor containment and bounded, clipped reference-plane polygons within one measurement. Native integer polygon subtraction and its four-square-internal-unit rounding allowance are unchanged. New measurements rebuild geometry after board edits.
- Prepare shared return-path spatial queries only where queried; retain the original point/ray/boundary tests.
- Use explicit CODATA 2022 scalar constants instead of importing SciPy for two numbers. These match the SciPy 1.17.1 baseline; optional older SciPy installations previously selected different CODATA editions.
- Build pad/terminal and test-point connection indexes once per operation. Saved snapshots reuse their terminal inventory; live editor net changes still reread the current board.
- Build one case-insensitive differential-pair name lookup per inventory instead of rebuilding it for each net.

No solver tolerance, mesh, selected path, physical assumption or result field was removed to obtain these timings.

## Fresh-process measurements

Three alternating before/after pairs per board. Each pair used a new KiCad Python process, loaded the unchanged board, then invoked `quick_si.analyze`. Before runs loaded original baseline modules using an import hook; after runs used the working source. Analysis timing includes imports after board loading. Process startup and initial pcbnew import are excluded. Results below are medians; simultaneous work caused substantial timing noise.

| Board and path | Analysis before | Analysis after | Speedup | Board load + analysis before / after |
|---|---:|---:|---:|---:|
| Marble, `/ETH_PHY/MII_MDC`, U6.8 → U54.16 | 7.086 s | 3.771 s | 1.88× | 9.105 / 5.844 s |
| White Rabbit import, `EBI1_NBS3`, IC33.J34 → IC6.A9 | 1.520 s | 0.515 s | 2.95× | 3.227 / 2.235 s |

Marble used the existing stackup screening with GND return review. White Rabbit used an explicit illustrative 50 Ω line, effective permittivity 3.2 and 50 Ω receiver; its imported board has no qualified physical stackup. These are different study assumptions, not a board-to-board accuracy comparison.

Full serialized report and path-data hashes were identical for every before/after pair:

| Board | SHA-256 |
|---|---|
| Marble | `4f26b2d985e37159e9c622cdc7e79d731c32133b3f2aff0c1462032c85fd695a` |
| White Rabbit | `9d95136023ffc48657339d8deb8ab933dcc9c0ea4b8881be6c137ee2f3ae3f9a` |

Marble resolved 253.67035313051676 mm and 1.7895671371906985 ns with status APPROXIMATE. White Rabbit resolved 62.554862085769486 mm and 0.3732633566036003 ns with status SCREENED. Equality proves the optimization preserves these results, not that approximate screening is a field-solver or laboratory validation.

## Native window loading

A complete Marble `SignalIntegrityFrame(saved_board=True)` still takes time. Three heavily contended alternating pairs ranged from 13.34–23.91 s before and 8.05–38.68 s after. A subsequent quieter single pair measured 13.517 → 12.421 s, approximately 8.1% faster. All pairs retained the same 28 test-point records and identical initial-state hash `c9d4e83b1066286e5b5f9309c51d46d711392231716646ff6c0225159b606472`.

These window measurements do not support claiming a large or universal GUI speedup. The targeted redundant scans were reduced, but native control construction, board loading and machine contention remain significant.

## Tests, guides and pictures

Native `python -m unittest discover -s signal_integrity_advisor_plugin/tests -v`: 203 tests run, 202 passed and one optional test skipped. The five added cold-import/index/corridor tests cover no SciPy scalar import, pair-rule equivalence, native clipped/full polygon equality including holes/boundaries, fresh geometry after edits and test-point metadata refresh.

The expanded [guide](../../signal_integrity_advisor_plugin/USER_GUIDE.md) documents every current tab/dialog, the literal CLI flags and controls, return setup, multi-pad terminals, IBIS loading/export, differential delay/phase, neighbour interference, reports, probes and Blender transfer. Complete HTML is packaged for offline help. Control inventories are coverage aids; the native tests do not exercise every possible interaction or operating system.

`help-marble-worked.png` and `help-white-rabbit-worked.png` are genuine native 1452 × 819 captures. PNG metadata is empty. Their stated uniform-line teaching assumptions differ intentionally from the Marble benchmark's stackup/return assumptions. Board hashes, endpoints, assumptions and limitations are recorded in the guide and [common example-board page](../QUICK_TOOL_EXAMPLE_BOARDS.md). Original boards were not modified.

The local reproduction evidence is retained under `.validation/si-exhaustive-speed/`: `bench_pair.py`, `run_bench.py`, `bench-results.json`, `bench_ui.py`, `ui-bench-results.json`, `ui-quiet-pair.json`, native test log and per-board capture/result records. Raw profiles contain local paths and are not distributed.
