# Third-party notices

Portable Web Export embeds an unmodified prebuilt distribution of **KiCad WebView**:

- Source: <https://github.com/wayri/kicad-webview>
- Pinned build: 1.1.0 at `9e0a72ee5bedf509e3a5fe2d213cad1d6844bffc`
- License: Mozilla Public License 2.0
- Matching source: <https://github.com/wayri/kicad-webview/tree/9e0a72ee5bedf509e3a5fe2d213cad1d6844bffc>
- Artifact: [Official npm archive](https://registry.npmjs.org/@wayrisignals/kicad-webview/-/kicad-webview-1.1.0.tgz)
- Archive SHA-256: `da0b378858ab5e66386f4ab1e4fb809aa346a481b195819ab5b7fdc7f8ef5263`
- Local integration inventory: `vendor/kicad-webview/PINNED-DISTRIBUTION.json`

That inventory is integration-authored; upstream supplies no `RELEASE.json`.
Retained upstream notices are unmodified and include historical source links;
the exact matching source for this build is the immutable commit above. The archived Pocket
source-available license is historical provenance, not an additional restriction
on the MPL-2.0 release (see upstream `LICENSING.md`). No demo designs or optional
integration dependency trees are included in this subset.

The packaged `vendor/kicad-webview/` directory and every generated HTML document must preserve the viewer's `LICENSE`, `LICENSING.md`, `THIRD-PARTY-NOTICES.md`, dependency/model notices and `SOURCE-PROVENANCE.json`. Those files, not this summary, are authoritative.

KiCad project designs and model assets retain their own licenses. Export only material you are authorized to distribute. This plugin does not grant rights to the user's design or its linked models.
