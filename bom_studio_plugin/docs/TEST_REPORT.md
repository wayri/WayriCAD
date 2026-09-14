# Test report — WayriCAD BOM Studio 0.8.3 full PCM

Executed 10 September 2026. Packaged developer preview; not a native KiCad-host, operating-system or manufacturer-portal certification. Current results supersede earlier versioned logs for this release.

## Executed results

| Area | Result | Boundary |
|---|---|---|
| Base 0.8.2 regression before editing | 1,061 passed | Establishes the supplied archive's baseline in this environment. |
| Complete modified backend suite | **1,132 passed**, no failures/errors/skips; 68.087 seconds | Original tests retained plus 71 assembler configuration, data, export, CLI, HTTP and pipeline checks. |
| Browser regression plus new acceptance | **315 checks passed** across 11 runners | Actual current DOM/JavaScript and authenticated backend, including 33 new assembler-workflow checks. |
| Independent Excel validation | Passed | artifact_tool imported one BOM worksheet, inspected numeric quantities and exact leading-zero MPN, found no formula errors, rendered output for visual review. |
| Python 3.10 syntax | 90 files passed | AST compatibility only; actual runtime Python 3.13.5. |
| JavaScript / shell syntax | 14 JavaScript files and 1 shell launcher passed | Includes current assembler script. |
| PCM schema/icon/archive/final extraction | Recorded in adjacent PCM_VALIDATION receipt | The exact final ZIP is checked against pinned official schemas and re-extracted for a full backend rerun. |

Per-run browser counts: browser_smoke 14, browser_v2 22, browser_v3 22, browser_v4 23, browser_v5 42, browser_v6 35, browser_v7 24, browser_v8 26, browser_nativefirst 43, browser_vendors 31, browser_assemblers 33.

Captured current results are in docs/validation-v083; screenshots in docs/screenshots/v083 show synthetic data. The separate final receipt identifies final archive hash, clean-extraction test result, deterministic rebuild and relocated-process checks. SHA-256 hashes establish consistency, not signatures or manufacturing approval.

## New coverage

Per-board quantities cannot inherit distributor routing, project board counts, attrition, MOQ or order multiples. Tests cover physical occurrence counts, DNP/BOM/board exclusion, preservation of fitted parts excluded only from placement files, named variants, explicit full reference lists and duplicate/case-only annotation failures. Existing source errors, missing required fields and rule-area uncertainty are not bypassed by mapping acknowledgement.

Field cases distinguish exact mapped blanks from automatic discovery, real descriptions from auto Value fallback, and assembler-specific LCSC codes from DigiKey/Mouser SKUs. Source/format identity conflicts remain errors. Output columns cannot remove required references, quantity, identity or package constraints; custom headers need review and formula-bearing identifiers/headings are refused. Tests confirm old vendor configurations, native BOM authority, native file bytes and component properties remain unchanged.

Exports exercise four-column JLCPCB CSV, single-sheet XLSX with literal full identifiers and numeric quantity cells, explicit TSV review, complete eight-profile ZIPs, excluded-parts audits, file hashes, no-demand output, no partial manufacturing files, source drift, stale preview and exclusive output creation. Settings save/reload, sidecar-only Undo and HTTP authentication are covered. CLI and release-pipeline tests exercise both successful output and failed gates with diagnostics but no BOM/upload files.

Browser actions exercise integrated navigation/profile cards, exact headers, unchanged 100-board/50%-attrition purchasing assumptions while producing ten per-board parts, required profile-review acknowledgement, real CSV/XLSX/ZIP downloads, custom heading review reset, mappings, saved drafts across navigation, top-level Save, full descriptions, optional nickname stripping, sharing, dark mode and compact page width. All previous runners load the new script as well as their retained workflow scripts.

## Execution boundaries

Direct localhost navigation was attempted and failed with `net::ERR_BLOCKED_BY_ADMINISTRATOR`. Browser acceptance therefore used an explicit Python HTTP bridge, injecting the shipped HTML/CSS/scripts and routing fetch to the real authenticated backend. Actual DOM interactions and downloads execute; normal browser navigation and full CSP/origin behavior are not established end to end. Separate HTTP security tests remain. Initial older-runner attempts omitted the system Chromium path and could not launch; the final complete rerun explicitly selected /usr/bin/chromium and passed.

Actual KiCad PCM GUI installation, Windows/macOS setup, WebView2/Qt/Cocoa desktop hosting, real IPC cross-selection/focus, native library loading/writeback, native job-set execution and KiCad 11 are **not executed**. Retained host/selection tests use injected contracts. Optional STEP conversion runs in retained tests in this environment; no optional dependencies or browser runtimes are bundled. Linux/Python 3.13.5 is the tested runtime; supported-interpreter syntax is not full cross-platform execution.

**No authenticated production assembler/distributor portal import has been tested.** JLCPCB/Sierra/PCB Power mappings are informed by their published fields. PCBWay/HQPCB/NextPCB/Seeed/Generic are explicitly review-required editable layouts, not certified current workbook clones. No CPL, Gerber, live inventory, supplier upload, reservation or order was added. Settings and generated reports do not qualify component compatibility or replace engineering review.

## Reproduce

From the installed plugin directory or plugins/ in an extracted source copy:

```sh
python -m unittest discover -s tests -v
python tests/browser_assemblers.py --chromium /path/to/chromium --output /new-results
python cli.py assemblers --list-profiles
python tools/build_pcm.py --output /new/WayriCAD_BOM_Studio_0.8.3_PCM.zip --schema-dir /official-schema-snapshots
```

Use --bridge only for the documented managed-browser restriction. Official schema snapshots are identified by pinned Git blob SHA in tools/validate_pcm.py. Browser tools/artifact_tool/jsonschema are development-time dependencies, not requirements for the offline BOM engine. Use disposable projects for native acceptance and back up working projects/catalogues.
