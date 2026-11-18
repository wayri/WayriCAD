# Third-party notices

Portable Web Export embeds an unmodified prebuilt distribution of **KiCad WebView**:

- Source: <https://github.com/wayri/kicad-webview>
- Pinned build: 0.8.0 source-preview at `2945c855df8698af4dfe70fd6e31f729400c5eda`, not published npm/CDN 0.8.0
- License: Mozilla Public License 2.0
- Matching source: <https://github.com/wayri/kicad-webview/tree/2945c855df8698af4dfe70fd6e31f729400c5eda>
- Artifact: locally built and tested source-preview archive
- Archive SHA-256: `7312c12b89c696b68b69ef9538ec7bbee42ae4d9c8894b96968214e7a19eb1d9`
- Local integration inventory: `vendor/kicad-webview/PINNED-DISTRIBUTION.json`

That inventory is integration-authored; upstream supplies no `RELEASE.json`.
Retained upstream notices are unmodified and include historical source links;
the exact matching source for this build is the immutable commit above. The archived Pocket
source-available license is historical provenance, not an additional restriction
on the MPL-2.0 release (see upstream `LICENSING.md`). No demo designs or optional
integration dependency trees are included in this subset.

The packaged `vendor/kicad-webview/` directory and every generated HTML document must preserve the viewer's `LICENSE`, `LICENSING.md`, `THIRD-PARTY-NOTICES.md`, dependency/model notices and `SOURCE-PROVENANCE.json`. Those files, not this summary, are authoritative.

KiCad project designs and model assets retain their own licenses. Export only material you are authorized to distribute. This plugin does not grant rights to the user's design or its linked models.
