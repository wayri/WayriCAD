# WayriCAD 4.8.7

## Shared Viewer Refresh

Review and Portable Web Export use the same tested KiCad WebView source build
at `470e9d1638b8f2af0af7e26928a04b1ad459b8eb`. Its package version is 0.8.0,
but these newer source-preview bytes are **not** the published npm/CDN 0.8.0
artifact. The immutable commit, source-build archive hash, per-file hashes and
matching MPL-2.0 covered-source link are retained in both independent pins.
No upstream package/store release or WayriCAD 4.8.6 asset is replaced.

- Shared native schematic/text rendering, saved scopes, tables/images/links,
  source selection and multilayer/3D inspection come from the tested viewer.
- Portable Web Export uses the occurrence-aware shared ProjectTree and
  photoreal-fast 3D controls, with reversible Expand and contextual inspection.
- A stale WayriCAD sidebar selection is cleared when a new source is loaded.
- Export metadata separates the viewer's commit and source-preview identity
  from the WayriCAD exporter version. Source-byte mismatch rejection and
  original-versus-bundled hash traceability remain intact.
- Review's classic/ESM asset checks preserve independent installation, bounded
  local serving, legal notices and exact source-build integrity.

## Validation And Limits

The pre-release source integration passed the complete hosted matrix in run
44358394529: seven Python/platform jobs plus the PI reference benchmark. The
version-aligned release commit and final assets require their own CI receipt.
Local checks additionally exercised KERO desktop and 390-pixel iframe exports,
native KiCad Review WebView loading, and retained PI/SI/steady/transient thermal
producer/consumer data. See [scope and reproduction](audits/WEBVIEW_SOURCE_REFRESH.md).

Local Windows custody-test failures remain recorded rather than hidden; the
corresponding full hosted suites passed without relaxing custody checks. An
initial hosted Windows Node decoder timeout did not recur on the fresh matrix;
the decoder assertion and timeout were unchanged.

No live-provider, native-editor IPC, all-platform native GUI or physical-phone
qualification is claimed. A saved field is not new solver validation. Missing
saved elevation and missing project-variable values are not guessed. Registered
fields/measurements pause during Expand and resume at the assembled pose.
