# WayriCAD 4.6.0

This release adds **Portable Web Export** as the 27th independently installable
WayriCAD package. It creates one self-contained offline HTML review and
assembly-tracking page from selected saved KiCad content.

## Portable Web Export

- Select saved schematic sheets, the complete saved PCB, BoM/tracking data and
  supported WRL/GLB/GLTF models independently.
- Resolve missing or unsupported assets in preflight, then render the exact
  generated page in an embedded `wx.html2.WebView` before export.
- Cross-select linked schematic, PCB, 3D and BoM content using saved UUIDs where
  available and exact references as a bounded fallback.
- Track ordering, receiving, assembly, DNP and notes in browser-local state,
  with project/revision-bound JSON backup and explicit migration.
- Retain UTC generation time, exporter/viewer versions, project, revision and
  document IDs, plus SHA-256 and byte counts for every bundled source.
- Operate offline with a restrictive content-security policy and no network
  requests. The page contains selected design bytes and must be shared only
  with authorized recipients.

## CLI and documentation

- `wayricad-portable-export` and `wayricad tools run portable-web-export -- ...`
  expose the saved-file exporter for controlled automation.
- Repeatable `--sheet` and `--model` globs, independent view exclusions and an
  optional separate JSON manifest support CI and KiCad jobset command steps.
- The expanded illustrated guide documents the native and recipient workflows,
  all options, exit behavior, traceability fields, recovery, troubleshooting,
  supported 3D formats and security/engineering limitations.
- The main catalogue and unified CLI catalogue now list all 27 packages and the
  new headless export surface.

The guide images are deterministic, source-aligned illustrations using generic
example data. They document the intended controls and page structure, but do
not establish a live-editor acceptance run.

## Compatibility and limits

Portable Web Export reads saved files; unsaved editor changes are not included.
The generated page is a review and tracking artifact, not an editable KiCad
project, ERC/DRC result or manufacturing approval. STEP and IGES models remain
labelled proxies because the pinned portable viewer does not decode them. Input
design/model bytes are limited to 64 MiB by the viewer contract.

KiCad 10 remains the native validation target. KiCad 11 support remains
experimental. Automated source, archive and CLI checks do not establish live
GUI compatibility on every supported platform; see
[compatibility](COMPATIBILITY.md) for the repository-wide evidence boundary.
