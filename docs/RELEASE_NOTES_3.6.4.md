# WayriCAD 3.6.4 release notes

Mechanical Check can now compare two saved KiCad boards in one 3D coordinate
frame. Select a comparison board, enter its X/Y/Z translation and Z rotation,
then run **Exact 3D solids**. The review distinguishes exact solid overlaps
from below-limit clearances between components and substrates on different
boards. Select a finding to inspect its contact in the native 3D viewer and
open an X, Y, Z or custom-direction cross-section. The offline HTML report
includes the same per-finding section curves and a 3D cutaway control.

The check uses KiCad STEP exports and FreeCAD/Open CASCADE. Both boards need
saved files and resolvable STEP models; unresolved comparison-board models
keep the result incomplete. Translation is in millimetres relative to the
current board's STEP export origin. Rotation is around Z, so perpendicular
board mounting is not yet represented. Cross-sections are exact cuts of the
imported solids; a plane that misses a body has no curve. Board and model
changes require a new run. The exported report excludes the comparison
board's local file path.

All 17 independently installable PCM packages use version 3.6.4. Update the
Mechanical Check package in KiCad 10's Plugin and Content Manager, then
restart PCB Editor. Other packages receive the aligned suite version without
new feature changes in this release.

Validation includes 33 Mechanical Check tests on Windows with KiCad 10 and
FreeCAD, including native collision, near-clearance and distant-board cases,
source-file preservation, cross-sections and offline report output. Source
documentation validation passed. The wider repository suite had 333 passes,
77 skips and one unrelated Windows subprocess-handle failure in a Trace RLC
CLI test; this release does not claim that test passed locally.


## Project Fusion addition

Project Fusion 0.9.2 is an additional independent testing package. It provides visual saved-project/subsheet merging, draggable layout and root-sheet placement, source-copy issue repair, BOM/fields and linked updates. Its native SWIG entrypoint deliberately excludes IPC discovery. Whole-project apply requires saved and closed target editors; live schematic import is unsupported. Existing 3.6.4 ZIPs, wheel, source archive and resource archive are not replaced. The original tag predates this addition; Fusion source provenance is supplied separately.
