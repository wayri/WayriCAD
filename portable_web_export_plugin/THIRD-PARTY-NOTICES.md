# Third-party notices

Portable Web Export embeds an unmodified prebuilt distribution of **KiCad WebView**:

- Source: <https://github.com/wayri/kicad-webview>
- Pinned build: 0.8.0 source-preview at `470e9d1638b8f2af0af7e26928a04b1ad459b8eb`, not published npm/CDN 0.8.0
- License: Mozilla Public License 2.0
- Matching source: <https://github.com/wayri/kicad-webview/tree/470e9d1638b8f2af0af7e26928a04b1ad459b8eb>
- Artifact: locally built and tested source-preview archive
- Archive SHA-256: `9a811d850854a5db8bf834213bcd2394af0f6d3c6ab8481b44257bca5b106e45`
- Local integration inventory: `vendor/kicad-webview/PINNED-DISTRIBUTION.json`

That inventory is integration-authored; upstream supplies no `RELEASE.json`.
Retained upstream notices are unmodified and include historical source links;
the exact matching source for this build is the immutable commit above. The archived Pocket
source-available license is historical provenance, not an additional restriction
on the MPL-2.0 release (see upstream `LICENSING.md`). No demo designs or optional
integration dependency trees are included in this subset.

The packaged `vendor/kicad-webview/` directory and every generated HTML document must preserve the viewer's `LICENSE`, `LICENSING.md`, `THIRD-PARTY-NOTICES.md`, dependency/model notices and `SOURCE-PROVENANCE.json`. Those files, not this summary, are authoritative.

KiCad project designs and model assets retain their own licenses. Export only material you are authorized to distribute. This plugin does not grant rights to the user's design or its linked models.
