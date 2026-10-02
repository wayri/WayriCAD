# Project Fusion release addition

Fusion 0.9.3 joins the WayriCAD inventory as an independent MIT-licensed testing
package. Its native SWIG action loader retains `org.wayri.projectfusion` and
deliberately excludes IPC discovery. It needs KiCad 10's wxPython and native CLI;
it does not need another installed WayriCAD tool. Source tests and private
project data are excluded from the PCM payload.

Local checks on 2026-10-03, Windows, KiCad 10.0.6.50883 / bundled Python 3.11.5:

- Native Fusion suite: 166 tests, 139 passed, 27 skipped, with native GUI and
  insertion GUI checks enabled. Discovery intercepts the C++ registration
  boundary; it does not establish connected-editor live transaction acceptance.
- Source suite against 3.6.4: 344 passed, 68 skipped and 147 subtests passed on
  Python 3.14.
- Mixed-runtime package tests cover isolated menu registration, installer backup
  and stale package rejection. Native packages cannot include an IPC manifest.
- Official PCM schemas, payload Python syntax, icon sizes and standalone assets
  checked across 18 candidate archives. Source and packaged documentation checked.
- The extracted release ZIP registered its native action and constructed its wx
  dialog under bundled KiCad Python, with C++ registration intercepted. Isolated
  wheel CLI help and report assets passed, including Fusion.

Version 0.9.3 additionally guards editor action registration behind an existing
wx application. Standalone bundled-Python CLI help no longer triggers KiCad's
`PgmOrNull()` registration assertion. A native subprocess regression covers that
case. Windows short-path aliases are normalized in reconstruction and dependency
test fixtures, including the undo failure injection; production rollback checks
remain unchanged.

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

## Publication

Source integration: [PR 23](https://github.com/wayri/WayriCAD/pull/23). The [release CI matrix](https://github.com/wayri/WayriCAD/actions/runs/37056049900) passed all eight checks on the source commit recorded in the release provenance. macOS covers suite compatibility and portable protocol checks, not Fusion publication support.

Fusion PCM SHA-256: `593891391b33c534267e686a217e66ff989638d0aefc8f1301662576a79c1ea5`. Published package, source and resources were downloaded and checked against their local hashes. Every original release asset digest and size, all 17 existing PCM package entries and all existing repository icon bytes were preserved.

## Search discoverability

The public README names the supported KiCad workflows, links directly to Fusion installation and guides, and distinguishes native Fusion from IPC setup. The repository About description and GitHub topics cover project merging and hierarchical schematics alongside the existing analysis tools. These are discoverability improvements, not evidence of indexing or rankings.

GitHub controls the repository HTML metadata, robots.txt and domain-level sitemap. No owned documentation site or Search Console/Bing Webmaster verification is configured by this change; no indexing submission is claimed. Descriptive content and crawlable links follow [Google Search Central](https://developers.google.com/search/docs/fundamentals/seo-starter-guide) and [Bing discovery guidance](https://www.bing.com/webmasters/help/why-is-my-site-not-in-the-index-2141dfab).
