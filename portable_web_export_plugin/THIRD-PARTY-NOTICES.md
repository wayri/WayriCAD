# Third-party notices

Portable Web Export embeds an unmodified prebuilt distribution of **KiCad WebView**:

- Source: <https://github.com/wayri/kicad-webview>
- Pinned version: official `v0.6.0` archive, not an unpublished working tree
- License: Mozilla Public License 2.0
- Matching source: <https://github.com/wayri/kicad-webview/tree/v0.6.0>
- Official asset: <https://github.com/wayri/kicad-webview/releases/download/v0.6.0/wayrisignals-kicad-webview-0.6.0.tgz>
- Archive SHA-256: `668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4`
- Local integration inventory: `vendor/kicad-webview/PINNED-DISTRIBUTION.json`

That inventory is integration-authored; upstream supplies no `RELEASE.json`.
Retained upstream notices are unmodified and include historical source links;
the exact matching source for this archive is v0.6.0 above. The archived Pocket
source-available license is historical provenance, not an additional restriction
on the MPL-2.0 release (see upstream `LICENSING.md`). No demo designs or optional
integration dependency trees are included in this subset.

The packaged `vendor/kicad-webview/` directory and every generated HTML document must preserve the viewer's `LICENSE`, `LICENSING.md`, `THIRD-PARTY-NOTICES.md`, dependency/model notices and `SOURCE-PROVENANCE.json`. Those files, not this summary, are authoritative.

KiCad project designs and model assets retain their own licenses. Export only material you are authorized to distribute. This plugin does not grant rights to the user's design or its linked models.
