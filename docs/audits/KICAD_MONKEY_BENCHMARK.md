# KiCad Monkey capability benchmark — 2026-09-20

Ran native KiCad 10.0.5 analysis against **142 distinct PCB contents** from 219 archived board files, then all **18 distinct project boards** (19 files; two assembly boards have identical contents) through PI, SI/RLC, decoupling, return-path and saved manufacturing checks. The 77 duplicate board files are excluded from inventory denominators. Additional SI coverage includes 27 routed boards outside `projects/`; combined SI path counts are deduplicated by board SHA-256.

**Result:** 141/142 distinct boards loaded. SI produced 30 complete first-order screens, 78 incomplete screens and 3 unresolved paths across 111 sampled endpoint paths on 40 distinct routed boards. PI completed both requested meshes on 12 project boards. These are capability/coverage results, not design acceptance or a field-solver accuracy score.

## Provenance and method

- Upstream: [wavenumber-eng/kicad_monkey](https://github.com/wavenumber-eng/kicad_monkey/tree/bc6796c1b8ce55bfbcb8b1771f3ecbc70658d34d), commit `bc6796c1b8ce55bfbcb8b1771f3ecbc70658d34d`.
- Archive: upstream `tests/corpus/kicad.archive.toml`, 266,556,039 bytes, SHA-256 `12a23e9849579198395a2a0d58aa8d8c368f08d6fa9612fb9439d765255e8b71`. Size and hash verified before extraction.
- Extracted only 936 PCB/project/schematic files into `.validation/kicad-monkey/corpus`. No upstream Python code was imported. All extracted design-file hashes remained unchanged.
- Windows, native KiCad 10.0.5 Python; NumPy 2.4.2, SciPy 1.17.1, VTK 9.6.1. Detailed interpreter/platform and working-tree engine hashes are in the JSON evidence.
- This is a modified 3.2.0 development working tree, not a released-build benchmark. Engine hashes were captured during the run and checked afterward; earlier operations are not bound to a before-run engine snapshot. No changes occurred after that capture.
- Every operation runs in an isolated subprocess; 15 seconds for inventory, 45 seconds for project/extra-SI operations. Native nonfatal wx logging is disabled to prevent modal dialogs during headless loading. Exceptions, refusal results and timeouts are retained.
- SI chooses up to three nets per board, preferring signal-like names and two-terminal nets, then fewer routed objects. Endpoints are the first sorted pad label and its farthest labeled pad; connectivity is established by the actual engine, not assumed from net labels.
- SI assumptions: 1 ns edge, 100 MHz, 20 ohm source, open resistive load, automatic reference selection; no forced Z0/permittivity. RLC skin-effect estimates sweep 1–1000 MHz. Unavailable frequency sweeps preserve the SI result.
- PI chooses one net per project with a power-like name preferred, then lower routed-object count. This deliberately bounds cost and is biased toward small paths. Net names such as `GPDI_SDA_5V` can match despite being signals. The selected terminals are arbitrary unit-current electrodes, not inferred regulator/load operating points.
- PI inputs: 1 V source, 1 A sink, 25 µm assumed via plating, meshes of 1.0 then 0.5 mm, default copper material/20 °C. No stackup override, zone refill, thermal pulse, operating-current claim, complete PDN solve, or source-board write.
- Decoupling uses `+*,VCC*,VDD*,VBUS*,VIN*,*3V3*,*5V*,*12V*` rails, `GND,*GND*,VSS` grounds, `U*` loads, `C*` capacitors and 3 mm distance. No findings may mean unmatched names, not absence of real decoupling needs.
- Return-path audits use actual saved filled reference polygons and copper-layer order. Manufacturing uses saved feature/rule minima against the demo profile; it does not measure clearance or run native DRC.

## Project coverage

`COMPLETED` means the operation returned, not that its findings passed. `NOT_APPLICABLE` means this selection/pattern found no eligible input. `BLOCKED` is a caught PI/model refusal. `ERROR` includes explicit guard exceptions (e.g. unsupported pad shapes). `TIMEOUT` means no result within 45 seconds.

| Project / board | SI paths (S/I/U) | PI | Decoupling | Return path | Manufacturing |
|---|---:|---|---|---|---|
| 4-ch-backplane / 4-ch-backplane | 3/0/0 | COMPLETED | COMPLETED | COMPLETED | ERROR |
| canbob / CANBOB (MAGE-CANBOB-003) | 0/3/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| celebration_led_assembly / celebration_LED_daisy_chain__A | 0/0/0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | ERROR |
| cern_wren_eda_04903 / EDA-04903-V1-0 | 3/0/0 | COMPLETED | NOT_APPLICABLE | TIMEOUT | COMPLETED |
| charge_indicator / 11-10043__charge_indicator__C | 3/0/0 | BLOCKED | COMPLETED | COMPLETED | COMPLETED |
| charge_indicator_assembly / 12-10005__charge-indicator-assembly__0 | 0/0/0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | ERROR |
| cm5_minima_rev2 / CM5_MINIMA_2 | 3/0/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| eez_dcp405plus / EEZ DIB DCP405plus front mask | 0/0/0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | COMPLETED |
| eez_dcp405plus / EEZ DIB DCP405plus | 2/1/0 | COMPLETED | NOT_APPLICABLE | COMPLETED | COMPLETED |
| icepi_sbc / cm0 | 3/0/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| icepi_zero_v13 / icepi-zero | 1/2/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| jumperless_v5r7 / JumperlessV5r7 | 0/3/0 | COMPLETED | COMPLETED | TIMEOUT | ERROR |
| kibuzzard / kibuzzard | 0/0/0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | COMPLETED |
| led_component / led_component | 0/0/0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | COMPLETED |
| nrf9151_feather / nRF9151_Feather | 0/3/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| speedy_processing_module / 11-10084__speedy_processing_module__B | 3/0/0 | COMPLETED | COMPLETED | COMPLETED | ERROR |
| taillight / 11-10045__taillight__C | 1/2/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |
| yoshi_mainboard / 11-10080__yoshi-mainboard__A | 1/2/0 | COMPLETED | COMPLETED | COMPLETED | COMPLETED |

S/I/U = screened / incomplete / unresolved. Zero paths are excluded from SI coverage rates. The archive includes assembly documentation boards and a front-mask board; they are retained as no-applicable-input cases.

## PI mesh sensitivity

Resistance is the selected copper-path ΔV/I, shown at the finer 0.5 mm mesh. The change is `abs(R1mm − R0.5mm) / abs(R0.5mm)`. Two meshes show sensitivity only; even a small change does not prove convergence or accuracy. Peak current density is more mesh-sensitive and is not certified by stable total resistance.

| Project | Net | R (mΩ) | R change | Peak J change | Solve wall time* |
|---|---|---:|---:|---:|---:|
| 4-ch-backplane | `Net-(J6-VCC)` | 3.21192 | 0.244% | 2.58% | 5.46 s |
| canbob | `/MCU_5V` | 39.96325 | 1.012% | 150.86% | 2.09 s |
| cern_wren_eda_04903 | `/SFP0/SFP_VCCR` | 1.57893 | 3.639% | 3.25% | 28.53 s |
| cm5_minima_rev2 | `Net-(T401-VCC)` | 2.42811 | 0.622% | 3.30% | 2.43 s |
| eez_dcp405plus | `Net-(IC1-AVDD)` | 2.92358 | 2.734% | 121.55% | 2.38 s |
| icepi_sbc | `Net-(U24-VIN_LDO_OUT)` | 0.90231 | 3.329% | 3.66% | 3.06 s |
| icepi_zero_v13 | `/GPDI/GPDI_SDA_5V` | 10.16696 | 2.267% | 26.71% | 2.38 s |
| jumperless_v5r7 | `+9V_C` | 13.67647 | 0.802% | 2.34% | 22.51 s |
| nrf9151_feather | `Net-(U2-PVDD)` | 1.24479 | 0.591% | 3.23% | 2.11 s |
| speedy_processing_module | `/TOP_LEVEL_IO/ZYNQ_PWR/TPS62A02_BUCK_3V3/FB` | 2.71155 | 0.185% | 0.08% | 4.30 s |
| taillight | `+5v0` | 4.28352 | 1.319% | 201.41% | 7.36 s |
| yoshi_mainboard | `+VBUS` | 39.58370 | 0.012% | 0.00% | 2.07 s |

*Includes board load, geometry extraction and both meshes/solves. One run per operation; inventory/additional SI sometimes ran concurrently. These timings describe this execution, not controlled performance comparisons or percentiles.

### Additional refinement of sensitive cases

These three cases were rerun sequentially with 1.0, 0.5, 0.25 and 0.125 mm requested edges and a 60-second per-board budget. All source hashes remained unchanged. Peak J is the reported maximum cell current density at the same imposed 1 A; changes can reflect local geometry/mesh behavior and need investigation before hotspot/thermal decisions.

| Project | Edge (mm) | R (mΩ) | Peak J (A/mm²) | Result |
|---|---:|---:|---:|---|
| canbob | 1.0 | 39.55901 | 311.782 | solved |
| canbob | 0.5 | 39.96325 | 124.287 | solved |
| canbob | 0.25 | 40.23295 | 111.215 | solved |
| canbob | 0.125 | 40.34990 | 319.416 | solved |
| eez_dcp405plus | 1.0 | 2.84366 | 329.078 | solved |
| eez_dcp405plus | 0.5 | 2.92358 | 148.534 | solved |
| eez_dcp405plus | 0.25 | 3.00997 | 93.581 | solved |
| eez_dcp405plus | 0.125 | 3.04425 | 95.407 | solved |
| taillight | 1.0 | 4.22701 | 356.462 | solved |
| taillight | 0.5 | 4.28352 | 118.263 | solved |
| taillight | 0.25 | — | — | mesh budget exceeded |

CANBOB resistance changes by about 0.29% in the last step, while peak J rises from 111.2 to 319.4 A/mm²: **peak J is not converged**. EEZ resistance still changes by about 1.13% in the last step. Taillight cannot reach 0.25 mm within the mesh-size guard. The charge-indicator baseline already fails at 1 mm. These are concrete numerical/coverage limits; no engine fix or claim of convergence is included in this benchmark.

## Gaps and follow-up priorities

- **4-ch-backplane / manufacturing:** Custom plated pad shape/padstack needs a native per-layer annular-ring audit.
- **celebration_led_assembly / manufacturing:** Saved PCB has no general/layer settings.
- **cern_wren_eda_04903 / return_path:** 45-second budget exceeded
- **charge_indicator / pi:** Further refinement exceeds the mesh budget. Increase mesh edge length.
- **charge_indicator_assembly / manufacturing:** Saved PCB has no general/layer settings.
- **jumperless_v5r7 / return_path:** 45-second budget exceeded
- **jumperless_v5r7 / manufacturing:** Custom plated pad shape/padstack needs a native per-layer annular-ring audit.
- **speedy_processing_module / manufacturing:** Custom plated pad shape/padstack needs a native per-layer annular-ring audit.

Priorities: refine PI paths with material resistance/peak-J changes through at least a third mesh; investigate mesh-budget failures on real rails; profile whole-board return-path scaling; review stackup/reference evidence behind incomplete SI screens; and extend saved manufacturing support for explicitly rejected custom plated pads. Keep unsupported cases visible until implemented.

One full-inventory fixture (`pcb_foundation/case260__coverage_missing_elements/input/missing_elements.kicad_pcb`) returned no native board. The other 141 distinct contents loaded, including empty/header-only fixtures; loading alone is weak evidence of electrical analyzability.

## Numerical checks and limits

Existing tests: **53 Quick PI**, **37 Quick SI**, **35 native RLC/return-path/uncertainty**, and **6 ordinary-Python RLC CLI** tests passed (131 total). The first combined native test invocation also attempted the pytest-based CLI suite and failed import because native Python lacks pytest; that suite was rerun successfully in ordinary Python.

Four independent analytical formula comparisons (three uniform-strip meshes plus two strips in series with a plated via barrel) have maximum relative resistance error **1.01e-13**. They verify simple linear DC assembly, material scaling and conservation; they do not validate extracted real-board geometry or high-frequency behavior.

The archive contains many SVG/netlist/reference assets; no `.s2p`, `.s4p`, `.spice`, `.cir`, `.raw`, `.ibs`, or `.ibis` files were found. No independent measured/field-solver PI/SI oracle was established. Do not report these corpus runs as a percentage accuracy, channel compliance, AC PDN impedance validation, crosstalk analysis or eye-margin certification.

## Reproduce

Use the pinned upstream archive above, verify its size/SHA-256, and extract its design files preserving paths. Third-party boards remain in ignored `.validation`; this repository stores the runner and compact evidence only. Use a fresh output directory for each run.

```powershell
$native = 'C:/Program Files/KiCad/10.0/bin/python.exe'
& $native tools/benchmark_kicad_corpus.py --corpus .validation/kicad-monkey/corpus --output .validation/kicad-monkey/inventory-new --operations inventory --timeout 15
& $native tools/benchmark_kicad_corpus.py --corpus .validation/kicad-monkey/corpus/kicad/projects --output .validation/kicad-monkey/projects-new --timeout 45
# --board-list accepts a JSON list of corpus-relative paths for additional runs.
# --operations si --paths 3 limits a run to the SI/RLC capability screen.
# --edges 1 .5 .25 adds a third PI refinement level (with the same per-operation timeout).
```

[Compact machine-readable evidence](KICAD_MONKEY_BENCHMARK_RESULTS.json) includes per-board hashes, statuses, timings, selected nets/endpoints, PI metrics, SI limitations and analytical references. Detailed local logs/reports are under `.validation/kicad-monkey/{inventory,projects,additional-si-final}/`; unit-test logs and the archive manifest are alongside them.
