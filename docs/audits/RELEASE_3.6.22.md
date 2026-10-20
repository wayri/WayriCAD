# WayriCAD 3.6.22 validation

This release packages shared-return PI, grouped source/load pad units, local SI
crosstalk, PI/Therm Sankeys and automatic geometry-based mesh sizing. Source
evidence is recorded in the [Marble analysis](MARBLE_COUPLED_ANALYSIS.md),
[power-diagram checks](POWER_SANKEY.md) and
[automatic-mesh checks](AUTOMATIC_MESH_SIZING.md).

Windows checks use the installed KiCad 10 native Python/wx/scientific runtime;
the portable root suite uses Python 3.14. Relevant source checks passed 494 root
tests with 88 skips, 80 native mesh/numerical/CLI tests, and native PI/Therm
control workflows. The new PI test uses the real frame-close path and exits
cleanly. The focused thermal UI check disables external STEP loading.

Saved Marble extraction/sizing and one selected power-path solve preserved
source bytes. Thermal feature omissions and the earlier thermal mesh-acceptance
failure remain documented; a good energy balance is not physical qualification.
The release does not assert native Linux/macOS GUI support or every live-editor
workflow from portable CI.

Candidate package, wheel and exact-source CI checks are release gates. Publish
the verified assets before promoting the PCM feed; never replace binaries under
an existing version. Uploaded asset hashes and public feed URLs must be checked
before declaring publication complete.

## Published release

- Source/tag: `8713237b4ea06b031a73854b8740c7a74a1996a3`.
- [All eight exact-source CI jobs passed](https://github.com/wayri/WayriCAD/actions/runs/39490027072): Windows/Linux Python 3.10, 3.12 and 3.14, macOS Python 3.12 and PI reference benchmarks.
- The final local PI suite passed 318 tests with 40 skips and 383 subtests.
  Manual sizing no longer computes automatic recommendations as a side effect.
- All 23 PCM ZIPs passed schema, payload, entry-point, icon and SHA-256 checks;
  offline help images passed validation. The corrected wheel passed isolated
  CLI, Analytics localhost API, report, transient and coupled-study checks.
- Fresh PI/Therm PCM extractions excluded checkout imports and exercised
  automatic meshing, analytical resistance/heat balance, CLI discovery and
  full/standalone Sankey HTML exports. Both native processes exited cleanly.
- [WayriCAD 3.6.22](https://github.com/wayri/WayriCAD/releases/tag/v3.6.22)
  contains 30 assets. GitHub upload digests and all downloaded bytes matched
  the local artifacts before PCM feed promotion. `SHA256SUMS.txt` accompanies
  the installers, source distribution, wheel, feed and repository resources.
- Source-archive text scanning found no private validation folders or literal
  personal Windows home paths. Existing published versions were not replaced.

The public PCM feed advances all 23 current packages only after those assets
are published and verified. The release is marked latest on GitHub.
