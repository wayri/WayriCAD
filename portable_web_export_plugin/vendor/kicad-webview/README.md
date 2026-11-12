# Pinned KiCad WebView distribution

This directory contains a minimal unmodified runtime/legal/API subset of the official
`v0.6.0` release archive from <https://github.com/wayri/kicad-webview>.

`PINNED-DISTRIBUTION.json` is a WayriCAD integration-authored inventory, **not** an
upstream release manifest. The upstream npm archive supplies no `RELEASE.json`.
It records the official asset URL and SHA-256, exact matching source tag, and
the byte count/hash and archive source path of every retained upstream file.
The classic runtime alone is used; full/lite ESM copies, demos, designs, models,
test fixtures, integrations and caches are not vendored.

Refresh reproducibly from the verified archive with:

```text
python portable_web_export_plugin/tools/pin_webview.py path/to/wayrisignals-kicad-webview-0.6.0.tgz
```

The helper refuses any archive other than SHA-256
`668f973db5e931ff32a68a7ee2dfd178d54d0be25ff47b24a5b460681a6d28a4`.
The runtime loader verifies every pinned file before generating an export.

Required release files:

- `kicad-webview.min.js`
- `LICENSE`
- `LICENSING.md`
- `THIRD-PARTY-NOTICES.md`
- `THREE-LICENSE`
- `FZSTD-LICENSE`
- `SPIKE-ENGINE-NOTICE.md`
- `SOURCE-PROVENANCE.json`

Do not edit generated viewer files here. Reusable viewer changes belong in the separate KiCad WebView repository. Update this pin only from a reviewed release and keep its source and third-party notices synchronized.

Upstream legal text is preserved verbatim, including older source-link references.
For this archive the matching source is <https://github.com/wayri/kicad-webview/tree/v0.6.0>.
The retained Pocket source-available text is historical provenance; upstream
`LICENSING.md` explicitly says it imposes no additional commercial restriction
on the software released here under MPL-2.0.
