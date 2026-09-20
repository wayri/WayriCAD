# Operating-work feedback: KiCad Monkey benchmark

The user requested fixes following the 2026-09-20 corpus benchmark. This document
tracks the engineering findings for the active WayriCAD operating/release work.
Baseline evidence: [benchmark](KICAD_MONKEY_BENCHMARK.md) and
[machine-readable results](KICAD_MONKEY_BENCHMARK_RESULTS.json).

## Required work and acceptance

| Priority | Observation | Required response | Acceptance evidence |
|---|---|---|---|
| P1 | CANBOB peak J changes from 111 to 319 A/mm² with finer mesh while total resistance nearly stabilizes | Diagnose mesh/flux conditioning and contact singularities; correct numerical defects; retain explicit unconverged status where physical peak convergence is unavailable | Analytical conservation/mesh tests plus repeated CANBOB/EEZ/Taillight refinement; no smoothing/clipping to manufacture agreement |
| P1 | Charge-indicator mesh guard fails at 1 mm; Taillight fails at 0.25 mm | Reduce unnecessary triangulation/refinement cost without raising budgets blindly or dropping contacts/holes | Actual source boards solve within existing budgets; area, boundary, electrical continuity and energy checks remain |
| P2 | 78 incomplete and 3 unresolved SI paths | Distinguish missing physical inputs from extraction/connectivity defects; fix demonstrated defects and report actionable blockers | Same selected endpoint paths; no guessed stackup, dielectric or reference plane used to inflate completion |
| P2 | CERN WREN and Jumperless return audits exceed 45 seconds | Profile and remove repeated global geometry scans | Equivalent findings on small controls; full native audits complete within original budget |
| P2 | Manufacturing refuses custom plated pads on three boards | Extend only defensible geometry support; otherwise report supported checks and precise unknowns | Custom/offset-hole regression cases and original board audits; unsupported geometry never passes |

Empty assembly boards and a front-mask board are non-electrical input cases, not
solver regressions. 141/142 unique PCB contents loaded; the lone load refusal is
a separate fixture compatibility investigation. 131 supporting tests passed.

## Verified outcome — 2026-09-20

Implemented and rerun locally with KiCad 10.0.5 bundled Python on Windows.
The baseline report is unchanged. Compact, reproducible before/after evidence
is in [fix results](KICAD_MONKEY_FIX_RESULTS.json); detailed native outputs are
under `.validation/kicad-monkey/` at the paths recorded there. All rerun source
boards and projects retained their original hashes.

| Area | Baseline | Verified result |
|---|---|---|
| Project PI at 1/0.5 mm | 12/13 eligible cases completed | 13/13 completed; charge-indicator now uses 168,420 triangles at 0.5 mm within the unchanged 400,000-cell budget |
| CANBOB at 0.125 mm | 177,871 triangles; peak 319.4 A/mm² | 10,199 triangles; peak 115.4 A/mm²; resistance 0.0404004 Ω |
| Taillight refinement | Budget failure at 0.25 mm | 0.25 mm completes with 130,216 triangles; 0.125 mm still refuses on budget |
| Return path: CERN WREN | Timed out at 45 s | Completed in 27.25 s |
| Return path: Jumperless | Timed out at 45 s | Completed in 13.00 s |
| Manufacturing: Jumperless/backplane/Speedy | Custom-pad extraction refused | All audits complete (6.85/2.40/2.01 s); proven annular violations remain FAIL |
| Same 111 SI endpoint selections | 30 SCREENED / 78 INCOMPLETE / 3 UNRESOLVED | Same classifications, now with actionable structured blockers; missing dielectric values are not silently invented |
| Automation ZIP return-path audit | Missing bundled differential-pair helper | Helper included; isolated installed audit imports and executes |

### Engineering changes

- PI uses constrained Delaunay triangulation, bounded interior seeds on complex
  planes, and local angle improvement. Region identifiers preserve terminal and
  material boundaries through subdivision. Area, boundary, manifold, cancellation
  and budget guards remain. No peak clipping, smoothing or raised budget.
- SI treats saved stackup data as authoritative when native wrappers omit it.
  Missing/invalid dielectric thickness or permittivity blocks the calculation.
  Reports distinguish missing references, unmodeled vias, disconnected routes,
  distributed zone paths and unsupported asymmetric internal-line geometry.
- Return-path checks index filled-polygon edges, reference regions, vias and
  differential-pair candidates. Point membership preserves outlines and holes;
  coupling searches account for both trace widths.
- Manufacturing retains independent checks when annular geometry is unsupported.
  Custom anchors and offset-hole estimates are explicitly conservative bounds:
  sufficient bounds can PASS; insufficient bounds are UNKNOWN. Separate exact
  violations can FAIL. Unknowns block release, and remain JSON-safe.

### Acceptance checks

- Repository unittest: 305 tests, 67 skipped, no failures.
- Repository pytest: 285 passed, 67 skipped; 138 subtests passed. These overlap
  unittest coverage and must not be added together as independent tests.
- Native suites: 56 PI, 38 SI, 8 manufacturing, and 40 focused
  trace/return/uncertainty/frequency tests passed. These overlap root tests too.
- Analytical strip resistance/current density, conservation of energy, sliver
  regression, winding, contact-region preservation, polygon-hole membership,
  wide-trace coupling and uncertain-pad release guards passed.
- Five standalone ZIPs built and imported under isolated native Python: Quick PI,
  SI Advisor, Trace Impedance, Manufacturing Readiness and Extract Pins automation.
  The last also executed its bundled empty return-path audit. This checks backend
  isolation, not a new GUI/theme acceptance run.

### Remaining limits and release handoff

CANBOB peak J remains mesh-sensitive (81.1, 95.3, 92.8, 115.4 A/mm² at
1/0.5/0.25/0.125 mm). The mesh defect is reduced; peak convergence is **not**
established. Taillight's 0.125 mm request remains beyond the existing budget.
The 78 incomplete and 3 unresolved SI paths still require missing inputs or
additional physical models/connectivity resolution. Existing explicit copper
and via-plating assumptions remain; this work does not remove every assumption.
The separate native refusal fixture remains a compatibility investigation.

No measured or field-solver oracle exists in this corpus. Successful execution
does not establish real-board accuracy, protocol compliance or manufacturing
readiness. No PCB edits, release publication or feed updates were performed by
this fix task. The concurrent release work owns the 3.2.0 metadata/feed transition;
the root test results above used its current candidate feed. Public-feed state
must be handled by that release workflow.
