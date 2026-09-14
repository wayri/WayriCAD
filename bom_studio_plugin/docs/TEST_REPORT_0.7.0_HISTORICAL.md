# Test report — WayriCAD BOM Studio 0.7.0

Executed **9 September 2026** (recorded execution-environment date). Developer preview. This report supersedes current-version asset-capture claims in earlier documents; versioned validation folders remain historical records.

## Executed results

| Test area | Result | Actual scope |
|---|---|---|
| Complete Python backend suite | **791 passed, zero failures/errors/skips** | 704 retained tests plus 87 asset, preview, catalogue-search, CLI and HTTP cases; approximately 35 seconds in this environment |
| Browser primary smoke | **14 passed** | Existing workspaces, editing, exports, themes and compact layout |
| Browser v0.2 / v0.3 / v0.4 / v0.5 regressions | **22 / 22 / 23 / 42 passed** | Templates, grouping, evidence, injected live-selection driver, search/bulk/pipelines and analytics |
| Browser v0.6 engineering regression | **35 passed** | Catalogue, review/reuse, variants, qualification, mass, purchasing and bounded viewport |
| New asset-browser acceptance | **24 passed** | No-project browsing, text/typed/asset filtering, symbol/footprint/VRML/STEP previews, dependency status, source sets, metadata, original download, native-library bundle, deletion of original sources, dark/compact interface |
| Total browser checks | **182 passed; no recorded page/console errors** | Actual shipped JavaScript/DOM and authenticated Python backend through the documented HTTP bridge |
| Original-file and portable-library checks | **Passed** | Byte-identical downloaded STEP, retained hidden/alternate model references and transforms, native ZIP model closure/hashes, preview/export independent of removed source directories |
| Optional STEP conversion | **Passed with actual OpenCascade wrapper** | cadquery-ocp 7.9.3.1.1; real conversion of original synthetic STEP in a bounded subprocess, including a browser-triggered conversion |
| Embedded-resource decoding | **Passed via system libzstd** | Bounded base64/Zstandard decoding and integrity checks; Python zstandard package was not installed here |
| Independent modern MMH3 cross-check | **13 vectors matched** | Compiled MurmurHash3_x64_128 implementation, lengths spanning block/tail boundaries; expected values retained in tests/fixtures_v7_hashes.json |
| Python 3.10 syntax | **65 files passed AST parsing** | Actual execution used Python 3.13.5; not a Python 3.10 runtime test |
| JavaScript / POSIX shell syntax | **9 JavaScript files and 2 shell scripts passed** | Seven GUI scripts, two retained capture-extension scripts; node --check and sh -n |
| Linux installation and upgrade | **Passed in isolated prefix** | Fresh installation, previous install backed up outside plugin-scanned directory, installed doctor reports version 0.7.0 |
| Actual KiCad host recorder | **UNAVAILABLE, exit 6** | No installed kicad-cli; native/manual host checks NOT_EXECUTED |
| Clean ZIP extraction | **Recorded in the separate PACKAGE_VALIDATION.json receipt** | Complete backend suite rerun from final code in a fresh extraction; ZIP CRC and every manifested file checked |

Captured results are in validation-v7/. Screenshots in screenshots/v7/ show the actual new interface with original, fictional synthetic models; they are not manufacturer CAD or qualification evidence. The final distribution receipt is adjacent to the main ZIP. Integrity hashes are consistency checks, not signatures, trusted authorship or engineering approval.

## New backend coverage

The suite checks local native symbol/footprint capture, supported symbol inheritance, saved-board UUID association/source precedence, project/global library tables, environment/project/custom variables, aliases, multiple model references, visibility and transforms. It exercises nested/owner embedded references, bounded decompression, checksum failure, missing/ambiguous paths, changed source files and settings, deliberate cancellation, duplicate/same-name assets, exact model bytes and exclusion of fonts/unrelated attachments.

Catalogue asset sets retain coherent observations rather than pairing unrelated geometry revisions. Tests cover atomic import/association validation, legacy metadata-only records, hash membership, asset retrieval across part revisions, native-library name/link generation, strict/partial completeness, back-side export refusal and warnings for external model dependencies. Original model downloads cannot overwrite files or masquerade as a native design-file output.

Search cases exercise custom text/numeric field predicates, declared units, unknown quantities, state/asset predicates before pagination, source-set all-three completeness and independent no-project operation. Preview cases exercise supported native shapes and visibility, correct relative pad angle, malformed-number refusal, SVG escaping/bounds, VRML transforms/triangulation, STL/OBJ input and subprocess isolation/limits. Mesh processing does not execute model scripts or retrieve remote dependencies.

CLI and HTTP cases cover search, harvest asset configuration, assets, SVG/mesh previews, original download, native exports, large data-only asset-plan input, unsafe output paths, schema/input failures, cancellation and absent optional converter reporting. Existing BOM edits, review controls and source-file safety remain in regression tests.

These are bounded cases and synthetic fixtures, not coverage of every real KiCad or CAD construct. Modern embedded checksum math has an independent compiled reference; legacy checksum handling was source-reviewed and exercised with synthetic fixtures, not certified against a corpus of real KiCad-generated files.

## Browser and renderer boundary

Direct navigation was attempted and failed with **net::ERR_BLOCKED_BY_ADMINISTRATOR**. Browser tests therefore inject this package's actual HTML/CSS/JavaScript into Chromium and route fetch requests through a Python bridge to the authenticated localhost server. Real DOM events, asynchronous tasks, dialogs, editing and browser downloads are exercised. Normal URL navigation, the complete production CSP and browser-origin behavior are **not validated end-to-end** by that mode. Separate backend tests cover authentication, Host/Origin and route restrictions.

The actual 3D renderer exercised in this environment was **Canvas2D**, including real STEP mesh conversion. The WebGL path is implemented but was not executed here. Canvas fallback is bounded to 5,000 triangles; this run does not qualify its appearance/performance for arbitrary large models. The 3D inspector shows one model in model-local coordinates; it does not apply stored footprint transforms to a calibrated assembly overlay. STEP appearance is neutral tessellation, not full material/annotation reproduction.

The existing live-selection regression still uses an injected PCB driver; it does not demonstrate a real schematic/PCB relay. Keyboard viewer actions, tooltips, labels, dark mode and compact overflow were exercised, but actual screen-reader and comprehensive accessibility acceptance remain outstanding. The retained 50,000-row synthetic bounded-viewport check is not a benchmark of native-project parsing or CAD conversion.

## Native host and operating systems

KiCad/kicad-cli were not installed. The real host recorder returned UNAVAILABLE; no native result is inferred from our own parser. Native plugin discovery, symbol/footprint/model library reload, native project writeback acceptance, official IPC transport, schematic focus, native job-set execution/output collection and genuine KiCad 11 behavior remain **unexecuted**.

Windows batch/PowerShell, Windows Python/CAD-wheel compatibility and macOS installation were not executed. This release was run on Linux/Debian 13, Python 3.13.5, Node 22.16.0 and Chromium 144.0.7559.96. Playwright, optional OpenCascade and compiled MurmurHash3 were development/test tools here; no CAD dependency, browser binary, font file or compiled hash library is bundled.

Native previews are inspection aids, not KiCad rendering parity or mechanical/pin/electrical qualification. External textures/material files and externally referenced geometry are not recursively captured. Back-side native-library normalization is refused rather than guessed. Unknown or unsupported input remains visible. The application does not install dependencies or modify global KiCad library tables automatically.

## Reproduce

From the wayricad_bom_studio directory:

```sh
python -m unittest discover -s tests -v
python cli.py doctor
python tests/browser_v7.py --chromium /path/to/chromium --output /existing/parent/new-results
python cli.py gui --engineering-demo --no-auto-link
python cli.py hosttest --project /absolute/disposable/Board.kicad_pro --directory /absolute/new-host-output
```

The browser acceptance runner needs Playwright and a browser. Its actual STEP assertion needs requirements-preview.txt installed into the same Python interpreter; core backend tests conditionally exercise optional capabilities when present. Add --bridge only for the managed-browser restriction. Read V7_WORKFLOWS.md for original-file/preview distinctions, limits, export installation and supported source paths. Use disposable copies for native host acceptance and back up the whole catalogue directory while WayriCAD is closed.
