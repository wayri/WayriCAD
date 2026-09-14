# Marble functional validation — WayriCAD 3.1

The source is Berkeley Lab Marble: 1,006 footprints, 41,044 tracks/vias and 12 copper layers. Tests use memory snapshots or disposable project copies; the original design is read-only. This document records actual operations, not a blanket certification of every board, GUI transport or numerical model. The [3.0 smoke record](MARBLE_SUITE_SMOKE_3.0.md) is retained separately.

## Operations expanded from the earlier smoke test

| Tool | Result and actual scope |
| --- | --- |
| BOM Studio | **PASS:** all 25 legacy screens upgraded in a project copy; 2,047 placement records preserved, 11 canonical/power-field restorations. Native XML retains exactly 998 components and 1,374 nets. U1's eight units across six sheets accept a BOM field edit and native CSV export. |
| Project Library | **PASS for available assets:** copied Marble project localizes 1,006 footprints, 215 symbols, nine unique real models and 1,007 schematic assignments into `local/`. Prepare/apply/native validation completes in 96.33 s after a separate 23.42 s normalization. Native XML preserves all 1,374 nets. Missing external models/default libraries remain explicit partial-mode warnings. |
| Harness Workbench | **PASS:** 371 real Marble connector pins extracted. A separately identified two-board native fixture passes connection mapping, bundle/splice, BOM, CSV, SVG and offline HTML export. Marble alone does not supply an external harness board. |
| Heater Designer | **PASS:** review/apply/undo/redo and native save/reload preserve 43 generated items including one via on a separate outlined coupon in a copied Marble board. Placement preflight now rejects occupied copper, same-net shunts, zones and keepouts. |
| Planar Magnetics | **PASS:** equivalent operations preserve 23 generated items including one via on a separate copied-board coupon. Geometry review no longer invokes the unrelated mechanical-motion solver. |
| Manufacturing Readiness | **PASS:** full native Marble DRC runs and reports 464 existing violations; release generation correctly refuses them. A separate clean native fixture passes DRC, a real three-Gerber jobset and a verified 19-file release ZIP. Failed DRC counts remain visible. |
| Return-Path Auditor | **PASS:** extraction reads 37,380 signal segments, 3,664 vias and 118 filled regions in 3.64 s. A 158-segment FMC/MDI audit completes in 0.33 s with seven findings. Coverage uses whole trace corridors and actual plane outlines/holes rather than bounding boxes and midpoint checks. |
| Trace RLC / Impedance | **PASS for stated models:** native connected trace/arc/via/zone paths, thermal contacts and finite-width paths around holes. The old 128-contact zone cutoff is removed. Fifteen native geometry regressions pass, including 150 contacts on one island. Numerical estimates and unresolved fields remain separate. |
| Signal Integrity Advisor | **PASS for stated models:** independently packaged copy of the corrected RLC engine, including arc and zone-navigation support. Nonuniform or unreferenced routes retain unknown global characteristic impedance instead of a fabricated scalar. |
| Variant Workbench | **PASS:** a copied migrated Marble project receives a named R62 DNP/value variant. Three native XML exports retain the overrides; all 1,374 nets, Default, untargeted variants and the copied PCB remain unchanged. Backup verification passes. |
| Quick PI | **PASS:** native geometry, mesh, solver, result views, console, HTML/JSON exports and analytical regressions. Real single-net and full-net results are below; mesh convergence is explicitly separate from successful execution. |

The heater/magnetics copied-board DRC runs complete in 87.03/79.90 s with 467/466 findings versus the original 464. The added findings are dangling fixture endpoints; no new clearance findings are introduced. These coupons are validation fixtures, not proposed production-board modifications.

Project Library also validates exported symbol defaults and native schematic caches, while each placed assignment keeps its own extracted footprint. Native parsing/reload, geometry fingerprints, stable repeated output names, stale-source rejection, rollback and backup restoration are exercised. The full localization preserves all 29 input files byte-for-byte in verified publication backups. Evidence: `project-library-acceptance.json` and `project-library-result.json` under the validation directory.

## Other plugin checks

| Tool | Actual operation |
| --- | --- |
| Bulk Label Editor | Three footprint values changed and undone on an in-memory Marble board. |
| Copper Balancer | A 6×6 mm F.Cu region produces 42 candidates and three accepted shapes after regional filtering; native unit tests cover commit/recovery paths. |
| Extract Pins | Exports 371 actual J* connector pin/net rows. |
| Fanout Generator | C43 via-in-pad proposals are correctly rejected for other-net copper clearance. Native fixtures cover advanced angles, paired fanout and stale-plan/apply behavior. |
| Mechanical Check | Full component/pad geometry is extracted. Complete solid review still requires the missing external CERN 3D model collection; missing solids are reported, not substituted. |
| PDN/Decoupling | Processes 5,156 connected pads and reports 43 rail/decoupling findings. |
| Protocol Constraints | Detects 229 assignments, exports managed rules and verifies idempotent merging. |
| Test Point Descriptor | Extracts 28 real test-point/function rows. |
| Via Stitching | A 4×4 mm GND patch's four candidates are correctly rejected for target-copper or footprint conflicts. |
| Visual Diff | Native Edge.Cuts SVG comparison between identical Git/working-tree snapshots produces self-contained HTML. |

## RLC and power-integrity values

- FMC1_LA_33_P, P1.G36 → U1.B10: 87.1239 mm, 31 tracks and two via transitions. MDI0_P, J4.11 → U4.28: 19.8799 mm and 124 tracks; modeled covered sections estimate 54.1179 Ω and total route DC resistance is 0.075325 Ω.
- +12V, R15.2 → R16.2: the local RLC region has 34.2935 mm² island area and 12.8798 mm² reference overlap, estimating 4.8664 pF. Full-island capacitance and terminal-corridor R/L have different scopes and are not combined into a claimed complete circuit.
- /Power/+12VS, C131.1 → Q4.1: corrected connected path is 40.54865 mm through a track, a via and two zones. Arcs retain exact arc length; bent zone routes retain actual voids and thermal-spoke geometry.
- Quick PI, Net-(R161-Pad1), U1.M6 → R161.1, 1 V / 1 A: native GUI/console solve uses 429 vertices and 455 triangles, with approximately 2.568 mV drop and 2.568 mW conductor loss. Net, mesh, result maps and offline reports were generated from this actual run.
- Quick PI, full +12V net, R15.2 → R16.2 at 1 A: 235,624 triangles at 0.5 mm edge size yield 0.489011 mV drop and 0.489011 mW loss. The 1 mm result is 0.408474 mV: **this mesh is not converged**. At 0.4 mm, 331,376 triangles give 0.544301 mV, an additional 11.31% change. Sharp/contact current-density peaks are particularly mesh-sensitive.
- Quick PI, full /Power/+12VS net, C131.1 → Q4.1 at 1 A: 60,248 triangles at 0.5 mm give 2.182053 mV; 217,823 triangles at 0.25 mm give 2.256597 mV. At 0.2 mm, 317,037 triangles give 2.268876 mV: the final resistance increment is 0.544%. Peak current density still changes by 3.75% and needs its own convergence assessment.

Quick PI meshes actual filled sheet copper, holes and thermal contacts on each layer and connects only physical plated barrels. It solves DC current distribution with current/energy checks. Series components contribute explicit R/L branches; copper and component losses are reported separately. The real console command `run pi U1.M6 R161.1 5mH+30m R161.2 U1.M5` passes at 1 V / 1 A with 52,825 triangles: 35.040172 mV drop, 5.040172 mW copper loss and 30 mW component loss. Stored inductor energy is 2.5 mJ. Inductance contributes stored energy, not steady-state DC voltage drop. The pulse risk map is an adiabatic temperature-limit screen, not a coupled thermal solve or certified fuse-opening prediction. Plated slots and backdrills are refused until their barrel geometry is represented accurately.

The board's saved stackup supplies 0.105454 mm dielectric separation, Er 4.5 and 0.035 mm copper for the earlier RLC examples. The separate manufacturer stack file differs and was not silently substituted. Quick PI requires actual saved thickness/Z data or an explicit complete override.

## Reproduce and inspect

Final local release checks: 148 root tests and 86 subtests pass (40 optional/native skips); Project Library runs 315 tests with 19 skips and no failures; BOM Studio runs 1,170 tests with two skips and no failures; Quick PI passes all 49 tests in native KiCad Python. The 21 independent PCM ZIPs pass official schema, entrypoint, icon, payload syntax and SHA-256 checks. The rebuilt wheel passes isolated CLI and bundled report-asset checks. All 27 original Marble source hashes remain unchanged.

```text
python tools/smoke_marble_suite.py --project .validation/marble/Marble/design
python tools/validate_marble_operations.py --help
python -m unittest discover -s quick_pi_plugin/tests -v
python variant_workbench_plugin/tests/validate_native_project.py --help
wayricad-pi Marble.kicad_pcb --net Net-(R161-Pad1) --source U1.M6 --sink R161.1 --voltage 1 --current 1 --html pi.html
```

Native numerical/geometry tests run in KiCad 10.0.5 Python. Generated evidence lives under `.validation/marble/`: `migrated-bom-result.json`, `migrated-bom-write-result.json`, `operations-final/verified-summary.json`, `variant-operations-verified/result.json`, `rlc-expanded-results.json`, `return-expanded-results.json`, and `quick-pi/`. Source hashes are checked against `source-manifest.json`.

CERN's public library [explicitly excludes its 3D model collection](https://gitlab.com/ohwr/cern-kicad-libs). Complete Marble model localization/solid checks require those original external bytes. KiCad 11 and a complete end-to-end live IPC click test of all plugins remain unverified; package acceptance and isolated native operation tests do not establish those claims.
