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
