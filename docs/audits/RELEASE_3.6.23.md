# WayriCAD 3.6.23 release validation

This batch integrates Silkscreen Label Placer 0.3.2 into the full suite. The
functional changes and native evidence are recorded in the
[silkscreen audit](SILKSCREEN_ASSOCIATION_0.3.2.md). It retains the
[previous analysis capabilities and limits](RELEASE_3.6.22.md).

The supplied project was used only through a disposable local copy. Its source
PCB hash remained unchanged. No owner board, local path, raw private report or
repair copy is part of the source changes or release payloads. The new preview
illustration is generated from the public synthetic 100-part fixture.

Functional evidence: Windows build 26300, KiCad 10.0.6, native Python 3.11.5,
wxPython 4.2.2 / wxWidgets 3.3.2. The 94 native plugin tests passed, including
geometry, typography, multi-exit routing, partial Apply review, manual-text
preservation, rollback and exact undo. Native DRC found zero issues on the
synthetic assembly. The larger copied-board run introduced no new finding/item
combinations but left unresolved originals; it is not full-board approval.

The suite version advances to 3.6.23 and Silkscreen Labels to 0.3.2. Five
unchanged native packages retain their previous versions and must remain
byte-identical to their earlier published assets. Version/display substitutions
in unchanged IPC implementations reuse prior functional evidence, with fresh
package/import checks. Portable CI does not establish native Linux/macOS GUI
support or all workflows connected to a live editor.

Release gates: build the 23 independent PCM ZIPs and wheel/sdist; run package,
documentation and isolated-wheel validation; inspect the final native
silkscreen ZIP; require all exact-source CI jobs; publish immutable assets;
download and verify hashes before promoting the public PCM feed.

## Local release checks

- Fresh shared suite: 494 passed, 88 skipped, 227 subtests passed.
- All 23 PCM ZIPs passed official schemas, independent entrypoints, Python
  syntax, icon/help assets and SHA-256 checks.
- The five unchanged native ZIPs match their 3.6.22 public download bytes.
- The 3.6.23 wheel passed isolated CLI/import, Analytics localhost, report,
  transient and coupled-study smoke checks. Source archive text scanning found
  no private staging folders or personal Windows home paths.
- Exact-source CI and public asset verification remain publication gates.

Independent final Silkscreen PCM verification matched all 27 payload files to
source (apart from expected initializer newline normalization) and validated
the normalized 64-pixel repository icon. A fresh isolated native process passed
12-part dense placement, actual glyph/pad/courtyard/board checks, exact undo/redo,
manual-text preservation and the 850-pixel references-only/custom UI. It exited
normally. This does not test live editor action registration or editor undo.
