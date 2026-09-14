# Test report — WayriCAD BOM Studio 0.8.0 PCM

Executed **10 September 2026**. This is a complete packaged developer preview, not KiCad-host certification, native-editor parity, or manufacturing qualification. Earlier validation folders/versioned guides are historical; this report takes precedence.

## Executed acceptance

| Area | Result | Scope |
|---|---|---|
| Complete Python backend suite | **916 passed, zero failures/errors/skips** | 823 retained cases plus 93 current field, finder, classification, library creation, desktop/mapping, CLI/HTTP and native-probe cases; 39.259 seconds in this environment |
| Primary browser smoke | 14 passed | Open/save, editing, variants, exports, themes |
| Browser v0.2 / v0.3 / v0.4 / v0.5 regressions | 22 / 22 / 23 / 42 passed | Templates, property edits, grouping, evidence, selection contract, search, pipelines, analytics |
| Browser v0.6 / v0.7 regressions | 35 / 24 passed | Engineering catalogues, reviews, mass, build planning, bounded viewport, stored assets, original downloads, actual STEP conversion |
| New v0.8 browser acceptance | 26 passed | Actual field discovery/editing, facets/categories/details/previews/comparison, three library-creation modes and new-catalogue attachment, dark/compact views |
| Total browser assertions | **208 passed; no recorded page/console errors** | All nine shipped UI scripts plus actual local authenticated backend through the HTTP bridge, not a running KiCad editor |
| Syntax | 78 Python files / 11 JavaScript files passed | Python 3.10 AST syntax check; actual runtime Python 3.13.5; nine UI and two capture-extension scripts |
| Parts-finder benchmark | Completed on 10,000 synthetic identities | Warm page median 29.614 ms versus prior finder 370.327 ms on the same data; details in BENCHMARKS.md |
| Host acceptance recorder | **UNAVAILABLE, exit 6** | No usable kicad-cli; native/manual checks remain NOT_EXECUTED |

Full captured data: `validation-v8/backend-916.txt`, `browser-results.json`, individual browser logs, `finder-benchmark.json`, `syntax.json`, and `host-recorder.json`. The separate `WayriCAD_BOM_Studio_0.8.0_PCM_VALIDATION.json` receipt records the final archive/schema checks, clean-extraction regression run, relocated-process check and deterministic rebuild. A receipt is an integrity record, not a signature or host approval.

## New regression coverage

Field tests preserve exact physical names even when custom Qty/Source/Assembly/Currency collide with computed aliases, intentional blank values, raw/resolved variables, counts, native labels/order/visibility, custom editing, read-only identities, Boolean exclusion polarity, duplicate cached-project instance lookup and alias-conflict errors. Numeric unit mappings work through exact-property column names; conflicting unit defaults fail rather than changing temperature interpretation. Legacy saved layouts are repaired only by explicit view actions.

Finder tests cover revision-aware derived indexing, lightweight page loading, category/manufacturer/lifecycle/asset predicates, explicit category precedence, reference/keyword conflicts, metadata missingness, no authoritative epoch mutation, and source assets. Browser tests catch cached-preview disappearance on rerender, old-catalogue context leaking after attachment, comparison limits and wrong default catalogue after creation. Typed filters may still scan candidate summaries; no unbounded speed claim is made.

Library tests exercise empty native containers/new catalogue, automatic catalogue creation from saved projects, selected existing-catalogue capture, symbol-footprint-model relinking, all assigned original models, new-only paths, reserved names, symlink refusal, strict/partial missing assets, immutable source data, revision/source drift, read-only cancelable preview, confirmation, ordinary failure rollback and manifest verification. Existing destination data is never overwritten. The GUI acceptance created real on-disk files, not only download mocks. Native reload is checked with WayriCAD's own parser/asset resolver, not KiCad itself.

Desktop tests use an injected webview contract: explicit desktop default, no silent browser fallback, native Save policy and session authentication. Mapping tests use injected SDK-shaped objects including canonical protobuf UUID paths, not actual IPC transport. Native BOM passthrough uses an injected CLI contract and tests `kicad-cli version`, help discovery, Boolean forms, default/no-op flags, saved-only acknowledgement, unmodified bytes and unavailable capability handling. A native CLI pass is NOT claimed.

## Browser execution and operating-system boundary

The managed environment blocks ordinary direct localhost navigation. Browser runners inject the actual HTML/CSS/all nine shipped scripts into Chromium and route fetch through an exposed Python HTTP bridge to the real localhost server. DOM interactions, async tasks, calculations, edits, SVG/Canvas previews and downloads are real. Full production CSP, direct navigation and browser-origin behavior are not end-to-end validated in that mode; separate backend tests cover authentication, Host/Origin, static allowlisting and endpoint contracts.

The current machine is Linux, Python 3.13.5, Node 22.16.0 and Chromium 144.0.7559.96. Actual OpenCascade conversion runs where tested; these development dependencies are not bundled. No KiCad/kicad-cli, official kipy transport, pywebview or Qt host is installed here. Consequently **actual PCM GUI installation, KiCad toolbar discovery, native library loading/writeback, WebView2/Qt/Cocoa window creation, Windows/macOS setup, three-way cross-selection/focus, native job-set execution and KiCad 11 operation remain unexecuted**. Windows dependency/runtime availability must be checked on the target system. The default desktop implementation is shipped, but injected tests cannot certify its host.

The native library creator does not register existing library tables, draw missing geometry, infer missing 3D files, overwrite a published snapshot or approve component compatibility. Model links use the selected absolute destination; moving it requires relinking. Missing source evidence is not a pass. Read-only categories/health reflect recorded metadata, not a live supplier feed. Actual screen-reader acceptance and complete accessibility remain outstanding. The 50,000-row bounded viewport case is a synthetic browser render, not native parser throughput.

## Reproduce

From the installed plugin directory (or `plugins` in an extracted copy):

```sh
python -m unittest discover -s tests -v
python tests/browser_v8.py --chromium /path/to/chromium --output /existing/parent/new-result
python tests/benchmark_v8.py --count 10000 --iterations 12 --output /existing/parent/new-benchmark.json
python cli.py hosttest --project /absolute/disposable/Board.kicad_pro --directory /absolute/new-host-output
python tools/validate_pcm.py /absolute/WayriCAD_BOM_Studio_0.8.0_PCM.zip --schema-dir /path/to/recorded/official/schemas
```

Add `--bridge` only for a restricted test environment. Browser runners need development-only Playwright/Chromium; ordinary BOM/CLI runtime does not. The source includes packaging code and pinned schema blob IDs; official-schema validation requires jsonschema and those exact external snapshots. Keep project/catalogue backups and use disposable project copies for initial native acceptance.
