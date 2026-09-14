# WayriCAD BOM Studio 0.8.2 — Test report

Executed 10 September 2026 on Linux / Python 3.13.5. Packaged developer preview, not native KiCad/retailer-site certification.

## Final code execution

| Check | Result | Boundary |
|---|---|---|
| Complete backend suite | **1061 passed**, zero failures/errors/skips; 71.735 seconds | 986 inherited tests plus 75 vendor-routing/file/CLI/HTTP/pipeline tests |
| Existing browser regression assertions | **251 passed** | All eleven current shipped UI scripts; retained workflows |
| New vendor browser assertions | **31 passed** | Actual mapping, routing, partial/export checks, downloads, persistence, native-authority preservation, dark/compact rendering |
| Combined browser assertions | **282 passed**, no recorded page/console errors | Actual DOM/backend through the documented HTTP bridge |
| Syntax | **87 Python files, 13 JavaScript files, 1 shell launcher** | Python 3.10 AST syntax; runtime above |
| Independent XLSX import/render | **Passed** with artifact_tool | One BOM sheet, correct headers, numeric quantities, literal leading-zero SKU, formula-free file; strict OOXML namespaces corrected after independent-reader rejection |
| Real KiCad and supplier upload hosts | **Not executed** | No usable KiCad/kicad-cli, Windows/macOS desktop, live IPC or authenticated distributor account |

`validation-v082/` holds backend, browser, syntax and spreadsheet results. The external final package receipt records exact archive hashes, official schema/icon/CRC checks, deterministic rebuild, clean-extraction regression and relocated-process checks. It is an integrity receipt, not a signature or certification. Older logs and guides remain explicitly historical.

## Vendor coverage

Tests verify exact supplier aliases and custom field mapping, separate vendor-specific versus generic SKUs, override signatures and variant scope, stale/missing targets, full ordering suffixes/leading zeroes, ambiguous suppliers, formula/control rejection, no implicit network use, DNP/BOM exclusions, no-demand audit-only packages, pooling constraints, board/attrition/MOQ/multiple accounting, unassigned reconciliation, deliberate PARTIAL-only ZIP handoffs, private audit separation, correct import headings, conventional OOXML namespaces and one clean worksheet, chunking with no truncated lines, manifest integrity, saved settings/undo, no native/default-format mutation, source/fingerprint drift, CLI stdin/exit codes/new-file policies, authenticated HTTP routes and fail-closed release pipeline publication.

The new browser run catches unsaved config being reset on redraw, routing drafts lost on navigation, save-to-sidecar behavior, stale preview detection, independent routing/edit selection, actual ZIP/Excel downloads, all chunk retention, shareable profiles without instance assignments, and small-viewport overflow. Public sample files contain fictional DEMO parts, not real supplier matches.

## Explicit limitations

The browser automation uses system Chromium and Playwright with an HTTP bridge: actual static HTML/CSS/JS is injected and fetch goes to the real authenticated local server. This exercises UI logic and downloads, not unrestricted normal-navigation CSP/origin behavior. Backend HTTP checks cover auth/origin separately. This release does not claim actual desktop-window creation, three-way KiCad cross-selection, native library reload/writeback acceptance, native job-set execution, Windows/macOS installation, genuine KiCad 11 support or screen-reader certification. Optional OCP conversion is exercised by retained tests where available; no CAD/runtime binaries or fonts are bundled.

DigiKey/Mouser profiles follow published upload/column-mapping workflows. Actual files were **not uploaded** to authenticated production sites; regional/account matching and limits may differ. CSV/XLSX are alternative encodings of the same demand, not multiple orders. No live prices/stock, cheapest-supplier decision, cart manipulation, inventory reservation, credentials or automatic order is added. Unknown source/rule-area population remains blocked by the independent adapter; vendor routing does not bypass those checks. MPN-only matching still needs manufacturer/packaging review on the supplier site.

## Reproduce

From installed plugin root or `plugins` in an extraction:

```sh
python -m unittest discover -s tests -v
python tests/browser_vendors.py --chromium /path/to/chromium --output /new/output
python cli.py vendors examples/vendor_splitting/BOM_Demo.kicad_pro --config examples/vendor_splitting/vendor-config.json --format zip --output /new/vendor-boms.zip
python tools/validate_pcm.py /path/WayriCAD_BOM_Studio_0.8.2_PCM.zip --schema-dir /path/pinned-schemas
```

Add `--bridge` only for the documented restricted-browser environment. Headless runtime uses the existing standard-library engine; Playwright/artifact_tool/jsonschema are development-only dependencies. The normal KiCad action remains desktop-only with its declared pywebview/IPC dependencies. Use disposable source copies for initial acceptance.
