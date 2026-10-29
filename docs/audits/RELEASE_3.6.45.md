# WayriCAD 3.6.45 validation scope

This suite integrates the Quick EMerge exploratory beta, Review, complete
project-local simulation saves and portable result exports. Publication uses
the exact source commit that passes the configured eight-job CI matrix. The
GitHub release notes identify that commit and CI run; this document records
local evidence and its boundaries.

## Local checks

On Windows, the shared source suite passed 883 tests and 514 subtests, with
130 skips. KiCad 10.0.6 / Python 3.11.5 / wxPython 4.2.2 passed 327 native
Review, simulation-library and picker tests, with one symlink-permission skip.
Skipped dependencies and platforms are not compatibility passes. These counts
precede the final EMerge helper integration; its 188-test focused gate is recorded in
[EMerge validation](../../quick_emerge_plugin/VALIDATION.md), and the final
combined source is checked separately in CI.

The actual public saved-board Quick PI, Quick SI and steady/transient thermal
producers were rerun for 3.6.45. The shared board retained SHA-256
`8d60e824376418fa4cad65d37c9d8c8dd5da60c5538b9bf0a11976dbb98f1e7e`.
Original arrays, nulls, units, time steps and source bindings passed the viewer
adapter checks. Producer checksums normalize Git CRLF/LF source conversion;
boards and result payloads retain exact-byte custody. See the public
[examples and provenance](../examples/pocket-kivi/README.md).

Review's actual native GitLab clipboard text and generated-image workflow
passed real publication and independent provider readback against an approved
private test issue. Downloaded PNG bytes matched the upload exactly, and board
bytes remained unchanged. The generated preview approval was programmatic.
The installed source and both CLI sessions were checked separately; manually
launching the final pane through the editor and OS drag/drop were not verified.
No private boards or authentication data are included in packages.

The All tools picker has native filtering and selected-row paint checks in
light and dark palettes, including discovery of an installed Review package
absent from the legacy registry. Its saved-board desktop route does not invent
an IPC session or access unsaved state.

## EMerge numerical limits

Quick EMerge is marked beta in its name and testing in PCM metadata. API and
workflow checks do not prove numerical convergence or agreement with a paper.
The antenna refinement study remains unconverged; finer response and boundary/
resolution sensitivity work is deferred until sufficient RAM is available.
The preserved finer mesh is not an accepted solved result. See the EMerge
validation record for exact software evidence and supported geometry.

## Distribution checks

The release pipeline checks official metadata schemas, independent PCM ZIPs,
assets, help images, wheel imports and source-archive contents. Uploaded assets
are downloaded and compared to local SHA-256 values before the release is
published. The public PCM feed is promoted only after its referenced assets
are available and verified. Existing releases are not overwritten.
