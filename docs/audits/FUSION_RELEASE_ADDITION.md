# Project Fusion release addition

Fusion 0.9.2 joins the WayriCAD inventory as an independent MIT-licensed testing
package. Its native SWIG action loader retains `org.wayri.projectfusion` and
deliberately excludes IPC discovery. It needs KiCad 10's wxPython and native CLI;
it does not need another installed WayriCAD tool. Source tests and private
project data are excluded from the PCM payload.

Local checks on 2026-10-03, Windows, KiCad 10.0.6.50883 / bundled Python 3.11.5:

- Native Fusion suite: 165 tests, 138 passed, 27 skipped, with native GUI and
  insertion GUI checks enabled. Discovery intercepts the C++ registration
  boundary; it does not establish connected-editor live transaction acceptance.
- Source suite: 333 passed, 68 skipped and 144 subtests passed on Python 3.14.
- Mixed-runtime package tests cover isolated menu registration, installer backup
  and stale package rejection. Native packages cannot include an IPC manifest.
- Official PCM schemas, payload Python syntax, icon sizes and standalone assets
  checked across 18 candidate archives. Source and packaged documentation checked.

Whole-project application remains offline: saved and closed target editors,
source/target hashes, reviewed candidates and backups. The limited live PCB
adapter remains unqualified against a connected editor; live schematic insertion
is unsupported. Linux is a target platform without native qualification evidence;
macOS and KiCad 11 are unsupported. Electrical findings still require engineering
review.

This addition does not replace published 3.6.4 packages, wheel, source archive or
`resources.zip`. A separately named Fusion PCM archive and source provenance can
be added to that release. Promoting PCM discovery requires preserving every
existing package entry and publishing a newly named resource archive first.
