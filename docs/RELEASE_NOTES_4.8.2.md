# WayriCAD 4.8.2

DFM / DFA Studio reliability, supplier discovery and manufacturing review
improvements. All 27 independent PCM packages and the Python distribution align
to 4.8.2; unchanged tools retain their existing capabilities and limitations.

## Manufacturing Improvements

- Searchable 24-process / 28-supplier library with compatible-layer filtering,
  exact-service selection, source references and collision-safe custom JSON
  profile import/export. Existing profile identifiers remain stable.
- Added OSH Park 4-layer, 6-layer and 2 oz/0.8 mm presets, verified against
  official service pages on 2026-11-11. Other profile source dates are retained.
- Manufacturing Readiness Manager links directly to the process workspace.
  Supported-value dropdowns and explicit process/quote confirmation remain
  separate from factual board layer validation.
- Native geometry loading/render extraction moved out of worker threads.
  Completed native evidence survives a separately disclosed preview failure.
  Failed/cancelled reruns clear old evidence; stale-source guards remain.
- Native courtyard, mask, silk and routing-end findings link to engineering
  checklist areas and corrective guidance, without claiming complete DFA coverage.
- Sortable finding rows preserve selection identities; row activation invokes
  guarded PCB cross-probing. Dedicated offline help describes the actual workflow.
- Headless vendor search, rule preview and source-bound audit commands:
  `python -m manufacturing_readiness_plugin.dfm_cli --help`.
- Legacy profile load/save failures are actionable; invalid profiles cannot
  overwrite saved profiles. Verification workers handle UTF-8 diagnostics and
  close/start races. UNKNOWN audit results keep release actions gated.

## Verification and Limitations

Local manufacturing suite and opt-in KiCad 10.0.6 native recovery checks were
run on Windows with task temporary output on D:. Native tests cover actual CLI
execution, GUI-thread preview extraction, preview failure retention, failed
reruns, invalid process values and incompatible layer rejection. Headless tests
cover catalogue integrity, custom imports, rule/source contracts and CLI errors.
The final release validation receipt records exact counts, hosted CI jobs and
artifact hashes. Skips are not compatibility passes.

No complete fabrication/assembly certification, 3D tool-access analysis, paste
process simulation, live IPC/editor acceptance across every OS or KiCad 11
qualification is claimed. Manual/unsupported checks remain UNKNOWN. Ordinary
project DRC and actual supplier quotation review are still required. No local
installation is performed on the low-space C: drive.
