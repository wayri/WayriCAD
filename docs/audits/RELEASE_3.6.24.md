# WayriCAD 3.6.24 release validation

This release updates the 17 IPC packages to 3.6.24 and Silkscreen Label Placer
to 0.3.3. The user-facing changes are described in the
[release notes](../RELEASE_NOTES_3.6.24.md). Native silkscreen evidence and
limitations belong in the dedicated Silkscreen audit.

## Local validation

The results below distinguish native Windows validation from portable source
checks. A version update alone is not validation. Exact-source CI and public
asset verification are required before publication/feed promotion.

- Native Silkscreen suite: **171 passed**, none skipped. Later focused checks:
  **15 UI**, **5 report** and **13 readability/search** tests passed.
- Default text-only whole-board: **720 attempted, 674 accepted, 46 unresolved**;
  **317 changed, 357 accepted unchanged**. No all-reference closure is claimed.
- Independent checks covered all 674 accepted glyphs/direct associations and 250
  retained legacy guide strokes: zero physical-ink violations and zero required
  association crossings. Native DRC **295 → 288**, zero new type/item pairs,
  zero unconnected items. Exact Undo and manual-text preservation passed.
- Explicit short-leader comparison: **677 accepted, 43 unresolved**, 320 changed,
  10 permitted guides used. Independent ink/association checks passed; DRC again
  **295 → 288**, zero new pairs and zero unconnected items. R164 remains
  unresolved in the whole-board run; bounded diagnostic success is not counted
  as whole-board closure. See the
  [Silkscreen audit](SILKSCREEN_WHOLE_BOARD_0.3.3.md).
- Shared suite: **494 passed, 88 skipped, 227 subtests passed**.
- Final source documentation links/images, all 23 PCM packages and wheel smoke
  passed. The extracted final Silkscreen package passed native placement, exact
  undo and 850px references-only UI checks; its read-only CLI preview/report left
  the saved fixture board hash unchanged.
- Five unchanged native package archives retain their previously published bytes.
- Saved-board guide attachment checks use the same bounded 2D envelopes as
  placement. All 10 fresh guides remained attached after reload; uncertain
  legacy artwork was retained. The 20 focused lifecycle tests cover rotated
  courtyard corners, moved annotations, cleanup and rollback.
- Native ownership/lifecycle and mocked MCP boundary tests passed. Real stdio
  testing with official MCP SDK 2.3.0 on Windows/Python 3.14 passed handshake,
  tool listing/settings, native six-part saved-board preview/audit and out-of-root
  rejection. All six synthetic labels placed; source hash remained unchanged.
  Live-editor MCP operation was not tested.
- Exact-source CI and public asset verification are publication gates; the
  published release links its source run and download checksums.

## Release gates

Before publication, attach only release-safe validation evidence, complete the
required package and documentation checks, inspect all 23 independent PCM
packages and the wheel, and verify exact-source CI. Confirm the five unchanged
native packages remain byte-identical to their previous release assets.
Publication and public PCM feed promotion remain separate maintainer actions.

Portable source checks do not establish compatibility with every KiCad GUI or
workflow connected to a running editor. The release notes and Silkscreen audit
must state the actual tested OS, KiCad version and native runtime when known.
