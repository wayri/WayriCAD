# WebView integration source refresh

## Pin and scope

Public upstream main was checked at `2945c855df8698af4dfe70fd6e31f729400c5eda`.
Package version remains 0.8.0; this **source-preview** is not the published
npm/CDN 0.8.0 artifact. The local source-build archive SHA-256 is
`7312c12b89c696b68b69ef9538ec7bbee42ae4d9c8894b96968214e7a19eb1d9`.
Both Portable Web Export's classic script and Review's independent ESM script
use the same artifact. Their pin receipts retain source links and file hashes.
MPL-2.0 and dependency notices are preserved. No upstream release, store entry,
4.8.6 binary or PCM feed was changed by this refresh.

Audit found these two runtime entrypoints; native PI/SI/thermal tools produce
portable data rather than bundling separate WebView parsers. No unrelated
SPIKE source was added. Historical screenshots keep their original provenance.

## Adopted behavior

The shared parser/renderers supply the newer native text/symbol transforms,
saved variable scopes, bitmap/table/link handling, selection presentation,
inner-layer inspection and reversible Expand behavior. Portable Web Export now
uses the public occurrence-aware ProjectTree rather than a flat sheet list and
requests photoreal-fast for 3D. Its sidebar clears stale selection when a new
drawing becomes ready. The viewer retains its own compact/contextual controls.
There is no guessed sheet-local electrical equivalence or native connectivity claim.

Export metadata records the viewer commit, artifact hash and source-preview
identity separately from exporter/package versions. Original/bundled source
hashes and stale-write safeguards remain distinct.

## Verification

- Exact upstream build: build:3d, build and 645 tests passed, no skips.
- Focused exporter/Review asset/host checks: 33 passed, two dependency-gated skips
  and six subtests; four Node control tests passed.
- Browser KERO offline export: native PCB/3D rendering, exact R1 and /ST11_OUT
  lookup, selection clearing, BoM-to-board navigation, six-sheet hierarchy and
  power subsheet navigation passed. Expand reached 100% and returned to 0%.
- Native Review WebView: KiCad 10.0.6 Python loaded KERO through its real bridge,
  preserved source SHA-256, remained unauthorized for publication and closed normally.
  Reproduce with `python tools/verify_review_webview_pin.py path/to/Encoder.kicad_pcb`.
- Browser producer/consumer harness: retained PI, SI, steady and transient thermal
  exports preserved original JSON (including units/coordinates), exact part
  selection, palettes, byte-mismatch rejection, exact reload recovery and disposal.
  PI native 3D and independent saved-XYZ fields mounted. The durable harness is
  `portable_web_export_plugin/tests/viewer_acceptance.html`; serve it with the
  pinned classic script and `docs/examples/pocket-kivi/` saved records/boards.

## Limits and outstanding gates

The full affected portable/Review run passed 471 tests and skipped seven, but
four unrelated Git-context tests failed on this Windows/Python 3.14 host.
Repeated isolated reads exposed an intermittent lstat/fstat `st_ctime_ns`
disagreement for newly written NTFS fixture files; Review conservatively rejects
that observation. Its custody checks were not relaxed. A separate direct run
also encountered an invalid inherited stdin handle. Targeted viewer tests and
actual native/browser rendering are separate evidence from this incomplete gate.

The requested browser viewport override did not apply: DOM width stayed 1706 CSS
pixels. A subsequent same-origin iframe supplied an actual 390x844 CSS-pixel
viewport. Its measured document width and scroll width were both 390; PCB and
3D navigation and Fit were exercised and visually inspected. Header view tabs
remain horizontally scrollable; the sidebar is independently scrollable.
This is an embedded narrow-viewport check, not a physical-device benchmark.
Native editor IPC cross-selection, live providers and
all-platform native UI were not exercised in this refresh.

KERO is the only design used for visual/native acceptance. Saved-result checks
use actual computed public synthetic WayriCAD fixtures, not measured hardware.
Missing project variables in the supplied KERO fixture remain unresolved rather
than invented. Independent thermal 3D needs declared saved elevation; no missing
elevation is guessed. Expand suspends registered fields/measurements until the
physical assembled pose returns. The separate unmerged cursor-probe development
branch remains intact; it is not falsely attributed to this public source pin.
