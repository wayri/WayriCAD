# Quick PI copper defaults and readable identifiers

Development source for 3.6.40. Windows validation used KiCad 10.0.6, its Python
3.11.5/wxPython runtime, and portable Python 3.14.2.

## Behavior

The initial layer is All copper layers (projected). A user's explicit physical
layer selection survives replacement of inventory/geometry/result layer choices.
Copper stays scoped to the selected/simulated nets unless the user clears Only
simulated nets. Board retains edges and holes; saved silkscreen has its own Silk
toggle, off by default. This removes the earlier coupling between board context
and silkscreen without suppressing copper or altering solver inputs.

Physical vias receive V1, V2 and following labels in Y-then-X reading order, with
saved identity resolving coincident objects. Declared axial segments share their
physical via label; report spans/coordinates distinguish segments. Unlinked mesh
barrels are not guessed to be the same via. Cells use one-based C1/C2 labels.
Labels apply within the extracted model and can change when its scope or mesh
changes. Raw IDs, saved PCB UUIDs, numerical arrays and selection targets remain
unchanged. Exported JSON includes the display mapping. Prepared via lookup and
cell labels avoid sorting the via inventory on every hover.

## Evidence

- Native startup/board-view suite: 16 passed, including both-layer copper, Silk
  exclusion, retained outline, toggle-on glyphs and preserved explicit selection.
- Readable-ID/report/analytics/fusing/capacity scope: 41 passed, one native-only
  test skipped, 17 subtests passed. Native ID/inspector scope: nine passed.
- Native startup/live/differential workflow batch: 15 passed; one harness module
  name was mistyped. The correctly named native inspector module then passed all
  four tests. The import error was not counted as a pass.
- Root suite: 650 run, 525 passed, 124 skipped and one native KiCad netlist
  subprocess exceeded its unchanged 30-second timeout during concurrent builds.
  That exact native test passed in isolation in 5.6 seconds afterward.
- All 24 candidate ZIPs validated; wheel isolated smoke passed. New PI/shared
  payloads matched their source bytes. Existing candidate outputs were reused.
- The genuine first-open screenshot uses public Marble +12 V saved copper.
  SHA-256 before/after:
  `482850dbaaef9157e2e98af765a3c0d4d9c9f800daae224a54bf10e0621f52b0`.
  All copper layers were selected and Silk was off. No mesh/solve or PCB write
  occurred. The screenshot was inspected after a full native paint cycle and is
  RGB without embedded metadata. It contains no private paths.

The preceding reporting commit's CI exposed Analytics' script-free export
requirement. The shared enhancer now offers static navigation/style without
JavaScript or a nonfunctional print button; Analytics uses that mode. The original
script-free assertion is retained, not relaxed. The complete Analytics/BOM suite
ran 1,288 tests: 1,285 passed and three skipped. Its focused v5 export scope also
passed all 146 tests. Source documentation validation and diff checks passed.

Candidate packages reuse the existing validation output directory. Public release
assets/feed remain unchanged; no original/private design was modified.
