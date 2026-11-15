# WayriCAD 4.8.4

## Scope

This patch retains the 27-package 4.8.3 suite, including its electrothermal,
magnetics, fabrication-net comparison and official KiCad WebView 0.6.0
integrations. No older beta.2 renderer or 4.6.0 integration code is substituted.

The two issues reproduced in the older integration worktree were already
addressed on current `develop`: scans bind component metadata to saved-source
hashes, and traceability distinguishes original from embedded file bytes.
This release preserves those fixes and strengthens final-write enforcement.

## Portable Export Traceability

- Native preview export and headless export recheck the saved PCB, discovered
  sheets and supported models before writing and again after temporary-file
  staging, immediately before atomic publication.
- A detected change aborts the write, removes only this operation's temporary
  file and leaves an existing export unchanged. Rescan and rebuild the preview
  before retrying. No project files are modified.
- `sourceFiles[].sha256` and `bytes` describe the original saved file bytes.
  `bundledSha256` and `bundledBytes` describe the exact embedded file bytes.
  `transformed` identifies model-path rewrites. Revision identity continues to
  describe bundled content; it is not a substitute for original-source hashes.
- Regression tests reproduce a reference change from U1 to U99, validate all
  original/embedded hashes and byte counts, and inject saved-file changes after
  page composition and during output staging.

The check is not an operating-system lock: another process can still edit a
source after the final check. Reports are revision-bound snapshots, not a
promise that their source files remain unchanged indefinitely. Unsaved editor
state is not inspected. Low-level document writes without a supplied source
snapshot cannot independently establish source freshness.

## Validation And Limits

The release attachment `validation-4.8.4.json` records the exact tagged source,
hosted CI results, local checks and asset hashes. `SHA256SUMS.txt` lists release
asset checksums. Source tests, isolated package imports and native controller
tests establish different contracts; skipped tests are not passes.

This patch changes no viewer UI or rendering engine. Browser/native rendering
acceptance from the older-worktree review remains unverified; no new visual
qualification is claimed. All numerical, native-provider and fabrication limits
in [4.8.3](RELEASE_NOTES_4.8.3.md) continue to apply.

## CLI

Use `wayricad-portable-export BOARD OUTPUT.html --manifest OUTPUT.json` after
installing the matching Python package, or
`python -m portable_web_export_plugin.cli BOARD OUTPUT.html --manifest OUTPUT.json`.
Choose new output paths. If a source changes, rescan/retry rather than reusing
stale component metadata. See the [complete guide](../portable_web_export_plugin/README.md).
