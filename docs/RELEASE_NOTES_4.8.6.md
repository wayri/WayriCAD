# WayriCAD 4.8.6

## QuickTherm reliability

- Run automatically includes valid known power when no sources are selected.
  Explicit selections are retained; unknown source watts are never invented.

- Compatible ideal-temperature fixture contacts sharing a mesh cell no longer
  prevent a solve. Shared heat flow is counted once; individual shares remain
  unknown. Conflicting temperatures are still rejected.
- Built-in layered thermal kernels use diagonally equilibrated sparse solves,
  bounded iterative refinement and componentwise backward-error checks.
- The shared electrothermal kernel now uses bounded radiation Newton steps,
  matching standalone QuickTherm's protection against first-step overshoot.
- Failed jobs clear the misleading running status in the results panel.
- Optional CalculiX runs can provision the pinned official Windows x64 2.23
  static solver into a private cache, with archive/binary checksums, an actual
  launch check, cross-process locking, atomic activation and provenance.
- Existing explicit solver paths and PATH discovery retain priority. CLI
  `--no-solver-install` supports offline workflows. Non-Windows platforms retain
  explicit OS-installed solver selection.

## Scope

No new general-purpose FEM backend, CFD, physical contact inference, or measured
temperature accuracy is claimed. Shared-cell fixture flux is a mesh-level
reaction, not independently resolved physical contact flux. Existing CalculiX
geometry restrictions remain. No public binaries from older versions are replaced.

Validation evidence is recorded separately before publication.
