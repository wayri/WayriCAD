# Trace RLC open-board impedance audit (KiCad 10.0.6)

This audit separates **PCB extraction**, **closed-form formula agreement**, and **physical accuracy**. A routed open-source board establishes copper geometry, not measured characteristic impedance. The comparisons below do not certify a fabrication stackup or frequency-dependent channel behavior.

## Inputs and provenance

- [Berkeley Lab Marble](https://github.com/BerkeleyLab/Marble), local saved board SHA-256 `3304ba37c2bd891849fc36b500cd940934aaf1f2013a95639c03564fb925c512`. Its embedded stackup was read without substituting a separate manufacturing document.
- [Berkeley Lab Marble-Mini](https://github.com/BerkeleyLab/Marble-Mini), source commit [`fd0d18e`](https://github.com/BerkeleyLab/Marble-Mini/commit/fd0d18ece617ad60b4d7705a722e69548a63c6da), board SHA-256 `12ef078529fec02dd7badffb50340a919c526e967060a0d6d5058ffcaf55eacf`.
- [RFsim validation board generator](https://github.com/NBalciunas/kicad-rfsim/blob/efa0ea9bd34b13f7819c6f2d4c02e78d34b116c3/validation/make_test_board.py) and [its independent CPWG/stripline theory checks](https://github.com/NBalciunas/kicad-rfsim/blob/efa0ea9bd34b13f7819c6f2d4c02e78d34b116c3/validation/run_cpw.py), pinned to commit `efa0ea9bd34b13f7819c6f2d4c02e78d34b116c3`. Generated boards are disposable test inputs; no third-party board or source is vendored into WayriCAD.

The RFsim boards are 30 mm uniform lines. Their generator defines 2.9 mm outer microstrip, 1.5 mm grounded CPW with 0.3 mm side gaps, and 0.6 mm symmetric internal stripline. Its test material assumption is εr = 4.5, with 1.53 mm dielectric and 35 µm copper. The generated `.kicad_pcb` files do **not** save those dielectric properties in KiCad's Board Setup; WayriCAD correctly returns `partial` with null Z0 on all three as saved. Numbers in the next table are a separate model-only comparison using the generator's declared dimensions, not an automatic board extraction result.

| Uniform geometry | Independent reference | WayriCAD model | Difference | Verdict |
| --- | ---: | ---: | ---: | --- |
| RFsim microstrip, 2.9/1.53/0.035 mm, εr 4.5 | 49.8 Ω theory in [RFsim README](https://github.com/NBalciunas/kicad-rfsim/blob/efa0ea9bd34b13f7819c6f2d4c02e78d34b116c3/README.md) | 48.568 Ω IPC-2141A | −2.47% | Preliminary single-ended estimate, not sign-off |
| RFsim symmetric stripline, 0.6/1.53/0.035 mm, εr 4.5 | 50.249 Ω from RFsim's separate wide-strip formula | 48.957 Ω symmetric stripline | −2.57% | Preliminary single-ended estimate; model difference is visible |
| RFsim grounded CPW, 1.5 mm width, 0.3 mm side gap | 50.977 Ω from RFsim's coplanar elliptic-integral formula | **unknown** | Not comparable | Correctly unresolved: no CPWG solver |

Before the topology guard, applying the microstrip formula to the CPWG dimensions would have produced **71.668 Ω**, 40.59% above the coplanar reference. The geometry guard now detects the nearby same-layer copper and reports `LATERAL_COPPER_UNMODELED` with null Z0. A synthetic native regression also checks this fail-closed behavior. The detector is deliberately conservative: it flags nearby copper, but does not measure a continuous side gap or claim CPWG impedance.

## Native saved-board results

Tests ran with KiCad **10.0.6**, bundled Python **3.11.5**, on Windows. Source boards were read only. Outputs were written to ignored validation files and were not added to the repository.

| Board and selected path | Extracted result | Electrical coverage |
| --- | --- | --- |
| Marble `/ETH_PHY/MDI0_P`, `J4.11` → `U4.28` | 19.87986 mm; 124 track sections; 0 vias | Embedded stackup read. 123 sections have modeled single-ended Z0; one lacks a verified reference plane. Overall status `partial`, global Z0 null. |
| Marble-Mini `/ETH_PHY/MDI0_P`, `J4.11` → `U4.28` | 27.88805 mm; 10 sections | Legacy board lacks usable filled reference/dielectric evidence for this path. Zero modeled Z0 sections; status `partial`. Its `stackup.csv` is a signal timing table, **not** a dielectric stackup. |
| RFsim microstrip / CPWG / stripline generated boards, `RF`, `P1.1` → `P2.1` | 30 mm and one track section each | All remain `partial` with null Z0 from the saved boards because dielectric thickness/εr is absent. With declared dimensions injected only for validation, microstrip and stripline evaluate as above; CPWG stays blocked. |

Differential-mate selection was also reviewed. It extracts each selected net as a separate path and reports length skew. It does **not** solve even/odd modes or differential impedance, and two single-ended Z0 values cannot establish Zdiff. The UI now states this explicitly. Arbitrary bends, layer transitions, asymmetric internal lines, embedded microstrip, broadside pairs, conductor-backed CPW gap variation, solder mask, copper roughness, dielectric loss and frequency dispersion remain outside the validated impedance model. R/L values have their own assumptions; via inductance is partial and plane corridor resistance is not a field solve.

## Reproduce

Use the exact board source/commit links above and generate the three RFsim boards with its KiCad 10 `make_test_board.py`. Keep them outside the tracked source tree. With KiCad's Python, run:

```text
python -m unittest tests.test_trace_hybrid -v
python -m trace_impedance_plugin.cli path Marble.kicad_pcb --net /ETH_PHY/MDI0_P --start J4.11 --end U4.28 --reference In1.Cu --output marble-rlc.json
python -m trace_impedance_plugin.cli path RFsim-CPWG.kicad_pcb --net RF --start P1.1 --end P2.1 --output cpwg-rlc.json
```

The numerical reference assertions are in `tests/test_trace_hybrid.py`. A test passes when an unsupported topology remains explicitly unknown; no test here claims measured impedance accuracy. For a sign-off workflow, add a qualified 2-D/3-D field solve or impedance coupon measurement with actual dielectric, copper profile, plating, mask and tolerance data, then compare mesh convergence and frequency range.
