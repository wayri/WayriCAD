# Mechanical inspection validation — 3.6.13 candidate

Validated on Windows on 2026-10-09. Mechanical Check is the only package version changed in this candidate. The public PCM feed and published 3.6.12 assets were preserved.

## Behavior and evidence boundaries

Exact 3D part queries use Open CASCADE distances and closest-surface witnesses from transformed STEP solids. The live session stores private BREP copies from the completed analysis, checks the source board/model/enclosure fingerprints before and after queries, and strips its session token from portable reports. Changing analysis input or clearing pending measurements invalidates obsolete callbacks. Closing a session cancels its worker without blocking the GUI on the kernel.

Quick 2D distances are between same-side axis-aligned footprint envelopes. Saved Edge.Cuts contours provide unfilled visual context only; concavity, hole loops and native arc tessellation are retained. Missing/open outlines remain unavailable. Neither outlines nor PCB bodies participate as components in the automatic nearest-part search.

Point rulers measure Euclidean distances between picked tessellated surface points. They are stored separately from minimum part gaps and never establish nearest-part evidence. Zero surface distance alone does not establish positive penetration volume. Failed kernel checks remain unknown and prevent a nearest-part claim when they could hide a closer candidate.

## Automated checks

| Check | Observed result |
|---|---|
| Complete Mechanical Check suite under KiCad Python | 57 passed in 47.394 s; no skips |
| Shared repository suite under Python 3.14.2 | 397 passed, 73 skipped, 152 subtests passed in 53.80 s |
| Candidate PCM build and validation | 19 independent ZIPs; official schemas, action manifests, icons, vendored runtime and Python syntax validated |
| Final report diagnostics and behavior | Focused Node/Python report tests passed after the final ruler-label and missing-evidence text updates |
| Native source window | Saved-board run, typed part pair, numerical envelope reference, actual ray picks, point ruler, nearest hover, GPU rendering, export, stale-callback rejection and clean close passed |
| Extracted Mechanical PCM window | Same native workflow passed in Quick 2D and with actual 3D STEP solids, with code and shared runtime loaded exclusively from the extracted plugin; exact J1/C3 gap 28.638274058 mm, separate picked-point ruler and nearest hover verified |
| Extracted Mechanical PCM exact pipeline | Four modelled components; uncached C2/J1 query returned 13.320688458 mm with exact STEP witnesses; repeated cached query matched; source hash unchanged |
| Final offline report in the in-app browser | Board outline, reference labels, separate gap/point labels, saved H1/C2 distance and actionable missing-pair result verified; no browser console errors observed |

The native runtime was KiCad 10.0.6, Python 3.11.5, wxPython 4.2.2 / wxWidgets 3.3.2, PyOpenGL 3.1.10 and FreeCAD 1.1.3. Native tests include rotated asymmetric/bottom-side models, exact interboard findings, contact versus positive-volume intersection, independent XY/Z diagonal clearance, source immutability, missing geometry, cancellation and cache lifecycle. Outline tests use actual KiCad segments, arcs/circles, a concave contour, circular cutouts and invalid outlines.

The first restricted shared-suite run failed on Windows sandbox temporary-file permissions. The recorded passing run used a workspace-local temporary directory and normal runtime access. Skips in the shared suite cover unavailable optional/native integrations; they are not passes. Linux/macOS native windows and KiCad 11 extraction were not verified by this candidate.

## Performance reference

For 80 actual FreeCAD box solids, the all-pairs reference made 3,160 unique distance calls. The indexed nearest-part results matched that reference for every part, including Euclidean witness distance within numerical tolerance.

| Fixture | Exact distance calls | Cache hits | Indexed search | All-pairs reference |
|---|---:|---:|---:|---:|
| Spaced boxes | 64 | 32 | 0.266 s | 12.064 s |
| Coincident boxes | 79 | 1 | 0.534 s | 22.559 s |

These timings measure the nearest search only, excluding import, STEP export, full collision coverage and tessellation. The dense zero-gap case can stop its nearest search immediately; full collision screening must still inspect all potentially colliding pairs. Performance depends on geometry and arrangement.

Native indexed picking matched brute-force ray hits on a 6,400-triangle fixture with fewer than 30 triangle tests per sampled ray. The offline index used nine triangle tests for a 20,000-triangle fixture. Section clipping retains a valid back surface when the front surface is clipped away. Native GPU buffers and offline WebGL buffers are reused across frames and released when their scene is replaced or closed.

## Screenshot provenance and limitations

`mechanical_check_plugin/help-measurements.png` and its packaged resource copy show the repository's synthetic saved-board validation fixture in the final native OpenGL viewport. The image was captured from the actual front buffer after checking for GL errors. It contains no personal path, private board or network address; no redaction or image retouching was applied. Gap values are conservative 2D envelope measurements, while the explicitly labelled point ruler uses picked locations. The board outline is visual context, not a substrate solid or mechanical sign-off.

Exact analysis still requires usable models and FreeCAD; missing coverage remains incomplete. Static geometry does not establish assembly motion, tolerance stacks or manufacturing acceptance. Offline reports can show saved part measurements and add point rulers; an uncached part gap requires a new native analysis/query. Snapshot hover witnesses do not automatically update after external design changes.
