# Tested source-preview pin

Built from public commit `470e9d1638b8f2af0af7e26928a04b1ad459b8eb`.
Package version 0.8.0 does not imply the published npm/CDN 0.8.0 contains this
newer source. No upstream release bytes were replaced.

`PINNED-DISTRIBUTION.json` is an integration-authored receipt with the source
commit, archive hash and retained file hashes. Matching MPL-2.0 covered source:
<https://github.com/wayri/kicad-webview/tree/470e9d1638b8f2af0af7e26928a04b1ad459b8eb>.
All upstream and dependency notices are retained verbatim. Historical notice
links do not identify this source build. No demos or unrelated SPIKE code are bundled.

Rebuild using upstream pinned dependencies: `npm run build:3d`, `npm run build`,
`npm test`, `npm pack --ignore-scripts`. Review any hash difference before pinning.
Refresh both independent plugin copies with:

```text
python portable_web_export_plugin/tools/pin_webview.py source-build.tgz --review-destination review_comments_plugin/vendor/kicad-webview
```

The tool accepts only the reviewed archive hash. Installed plugins never import
the other plugin's runtime. Keep the complete legal/provenance subset in exports.
