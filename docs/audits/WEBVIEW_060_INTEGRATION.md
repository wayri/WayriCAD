# Review And Offline Export: 4.8.3 Source Validation

Release association: **4.8.3**. This records local source
validation, not a hosted release CI pass or public-download verification. No
installed plugins, public feed or published release assets were updated by
the implementation checks. Disposable archives below are not final 4.8.3 assets.

## Upstream identity

The official [WebView v0.6.0 release](https://github.com/wayri/kicad-webview/releases/tag/v0.6.0)
was checked through GitHub's release API. The downloaded npm-format archive
matched the published SHA-256:
`668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4`.
The old dirty source checkout and unpublished 0.7.0 candidate were not vendored.

Review retains the unmodified full ESM distribution, Portable Export the
unmodified classic runtime. Each package contains its own required assets and
MPL-2.0/third-party notices. Integration-authored pin receipts are explicitly
distinguished from upstream manifests:

- [Review pin](../../review_comments_plugin/vendor/kicad-webview/REVIEW-PIN.json)
- [Export pin](../../portable_web_export_plugin/vendor/kicad-webview/PINNED-DISTRIBUTION.json)

The upstream release selectively incorporates read-only KiCad Online 0.12.94
rendering/inspection work. It does not supply extension comments, authentication,
editing, or engineering solver execution.

## Implemented boundaries

Review now works without a separate viewer installation. Public copied camera
and saved-selection APIs drive navigation; stale loads lose comment authority,
and displaced exploded geometry cannot carry assembled-position markers.
Hidden panes defer native browser/listener creation until first actual display.
Closed-window guards and private process-local browser profiles are retained.
Provider publication remains explicit and exact-scope/source-bound.

Portable Export adds exact part/net lookup and public inspection controls,
rejects ambiguous identities, uses inert text for saved labels, validates progress
imports, and preserves exact reviewed export bytes. Stale scans stop the write.
Original saved hashes and transformed bundled hashes are recorded separately.
Atomic output uses unique temporary files and rejects source-path aliases.

## Evidence

Windows Python 3.11, native wx controls, Node and Chrome checks were performed:

- Full Review suite: 457 passed, 6 skipped. Skips are not native compatibility
  passes. Provider responses remain mocked; no live comment was published.
- Existing and new Review Node contracts: 36 passed.
- Portable Export Python suite: 15 passed; host control Node suite: 4 passed.
- Root package-pin and UI/documentation contracts: 13 passed.
- Actual Online parser round trip passed against the 0.12.94 working parser,
  SHA-256 `b1f1909cfe6c8d94fe0c26e761325f16a4ac5218e16d5a9211dd935dc5b251bc`.
  This identifies tested working bytes, not an inferred public release commit.
- All 27 disposable PCM archives passed schema, syntax, icons and runtime checks.
  Extracted Review and Export archives passed isolated imports, asset validation,
  local-host/offline export construction and original-source immutability checks.
- Actual Chrome rendering used KiCad's public PIC programmer demo: 63 parts,
  111 nets, exact GND lookup through the page controls, property inspection,
  outer-tab 3D navigation and exploded inspection. Desktop and 390px layout
  checks passed with no page errors. The offline export attempted zero HTTP
  requests. Review used a labelled illustrative marker and a native-channel stub,
  not a live provider or running-editor connection.

See the [export screenshot receipt](../../portable_web_export_plugin/SCREENSHOT_PROVENANCE.md)
and [Review validation](../../review_comments_plugin/VALIDATION.md) for capture
scope. No linked model assets were supplied; component bodies use stand-ins.

An initial forced software-GPU 3D capture timed out; normal GPU selection passed.
This does not establish universal driver support. Embedded native WebView and
live KiCad/provider workflows still require separate acceptance. Saved source
connectivity is not a native netlist/ERC result; buses, hidden power pins and
repeated-sheet instances retain upstream limitations.
