# WayriCAD Embed3D 0.4.1 — executed test report

Build date: 10 September 2026. Linux container, Python 3.13. libzstd, Pillow and jsonschema are available. **KiCad, pcbnew, wxPython and kicad-cli are unavailable.** A direct dependency-source access attempt failed due to network DNS resolution; no native GUI execution is claimed.

## Executed suite

```text
WAYRICAD_EMBED3D_NO_REGISTER=1 python -m unittest discover -s tests -v
Ran 332 tests
OK (skipped=18)
```

**314 passed; 18 skipped; no failures.** The raw log is `test-run.txt`. Relative to 0.4.0, there are 23 additional passing tests and 3 additional skipped native tests. Prior pure-Python codec, model-transform preservation, source resolution, archive, extraction, relink, symbol/cache, filesystem-safety and package/icon checks remain in the suite.

## New regression coverage

`tests/test_scan_hotfix.py` has 22 passing tests:

- Five ownership/renderer-contract tests. The native-reference test double reproduces the old 0.4.0 double release and verifies the corrected association keeps the model alive, enumerates table values, and releases its final reference on view closure. AST inspection guards the runtime setup; stale item callbacks return safe values after a reset.
- Seventeen saved-file scan/controller tests. They use real temporary files, the actual scanner and actual Python worker thread with a deliberately headless wx/event-queue double. PCB-only, schematic-only and combined discovery, checkbox-independent visibility, rescans, missing models, empty files, search filters, invalid-source failures, view-refresh failures, worker-start failures, stale-row/action locks, diagnostic data and unchanged source bytes are covered.

One new archive test verifies that package validation rejects an injected manual `DecRef` call in the workspace module.

## Why 0.4.0's tests missed it

The earlier UI model tests exercised selection values and Reset counts but did not model the native-reference transfer performed by Phoenix's public `AssociateModel`. They therefore did not catch the extra release in actual window setup. The new regression explicitly models that sequence, using the upstream Phoenix 4.2.3 implementation contract. This is not represented as a reproduction inside a native KiCad process.

## Native tests still skipped

Eighteen tests require KiCad/pcbnew/wx/CLI and/or an actual display. The three new ones in `test_native_workspace.py` check that the native model is not deleted after association, native child enumeration after Reset, and the saved-file worker populating a real wx table.

No claims are made about execution on Windows/macOS/Linux GUI hosts, actual PCM/manual installation, native render/layout/high-DPI behaviour, real STEP display, PCB coordinate normalization, native embedded checksums/parser acceptance, schematic CLI netlist acceptance, or live-board undo/redo. The full native test suite and manual acceptance checklist remain necessary.

Synthetic model bytes test byte preservation, not valid STEP geometry. Headless controls are not screenshots or simulated visual proof. The older 0.4.0 report is retained under `history/` in the source distribution as historical evidence, not current assurance.

## Release checks

Current PCM/source archives are checked for version consistency, required runtime modules, root layout, PNG dimensions, unchanged icon bytes, Python syntax, duplicate/unsafe paths and ZIP integrity. The source archive is independently extracted and tested. The PCM's installed-style package layout is imported and its corrected association plus saved-file scan path are exercised with the same ownership double, not a native wx runtime. See `release-checks.txt` for actual results and `SCAN_HOTFIX.md` for the defect and references.

Full downloaded official PCM JSON-schema validation is not claimed. Built-in package-specific checks are executed, and the build accepts `--schema` for a locally supplied official schema.

**Release classification: testing hotfix for KiCad 10.0.x.** Start with a copied project; no KiCad 11, IPC, certification or production-ready claim.
